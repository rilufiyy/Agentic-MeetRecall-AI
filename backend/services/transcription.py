"""
Transcription service - providers:

  1. local      : Whisper (HuggingFace, runs on this machine) + pyannote 3.1
  2. groq       : Whisper Large v3 Turbo on Groq API (fast, free tier available)
                  + pyannote 3.1 for speaker labels (needs HUGGINGFACE_TOKEN)
  3. groq_fast  : Groq Whisper only, no diarization (every segment = Speaker 1)
  4. gemini     : Gemini 3.5 Transcribe (cloud, transcription + speaker labels in
                  one call, free tier available; up to 30 min with diarization)

Local models are loaded lazily, so a CPU-only machine that uses the Groq
providers never loads the local Whisper weights.

All providers return Tuple[List[TranscriptSegment], str, float]
(segments, full_text, duration_seconds) so downstream services are provider-agnostic.
"""
from __future__ import annotations

import abc
import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import List, Tuple

import torch
from huggingface_hub import login
from transformers import pipeline as hf_pipeline

from models.schemas import TranscriptSegment

logger = logging.getLogger(__name__)

WHISPER_MODEL_ID     = os.getenv("LOCAL_WHISPER_MODEL", "openai/whisper-large-v3")
DIARIZATION_MODEL_ID = "pyannote/speaker-diarization-3.1"


def _cuda_works() -> bool:
    """Test if CUDA is actually executable, not just available."""
    if not torch.cuda.is_available():
        return False
    try:
        torch.zeros(1).cuda()
        return True
    except Exception as exc:
        logger.warning(f"CUDA reported available but failed sanity check ({exc}). Falling back to CPU.")
        return False

_USE_CUDA = _cuda_works()
logger.info(f"Device: {'GPU (CUDA)' if _USE_CUDA else 'CPU'}")


# Utility 

def _check_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found in PATH - install ffmpeg.")


async def convert_to_wav(input_path: Path) -> Path:
    """Convert any audio/video to 16 kHz mono WAV (required by Whisper and Pyannote)."""
    _check_ffmpeg()
    output_path = input_path.with_suffix(".wav")
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {stderr.decode()}")
    return output_path


# Base Provider 

class TranscriptionProvider(abc.ABC):
    @abc.abstractmethod
    async def transcribe(
        self, audio_path: Path
    ) -> Tuple[List[TranscriptSegment], str, float]:
        pass


# Local Whisper (internal — used by WhisperSmallWithDiarizationProvider) 

class LocalWhisperProvider:
    """Local Whisper ASR (WHISPER_MODEL_ID). Used internally by the local provider."""

    _pipeline = None

    def __init__(self) -> None:
        # Loaded on first use, not at startup (heavy on CPU-only machines).
        self._device_int = 0 if _USE_CUDA else -1

    def _initialize_pipeline(self) -> None:
        if LocalWhisperProvider._pipeline is not None:
            return
        logger.info(f"Loading Whisper model: {WHISPER_MODEL_ID} on {'GPU' if _USE_CUDA else 'CPU'}")
        try:
            LocalWhisperProvider._pipeline = hf_pipeline(
                "automatic-speech-recognition",
                model=WHISPER_MODEL_ID,
                chunk_length_s=30,
                device=self._device_int,
                torch_dtype=torch.float16 if _USE_CUDA else torch.float32,
            )
            logger.info("Whisper loaded.")
        except Exception as exc:
            logger.warning(f"Whisper load failed: {exc}. Clearing cache and retrying on CPU...")
            cache_dir = Path("/root/.cache/huggingface/hub/models--openai--whisper-large-v3")
            if cache_dir.exists():
                shutil.rmtree(cache_dir, ignore_errors=True)
            LocalWhisperProvider._pipeline = hf_pipeline(
                "automatic-speech-recognition",
                model=WHISPER_MODEL_ID,
                chunk_length_s=30,
                device=-1,
                torch_dtype=torch.float32,
            )
            logger.info("Whisper loaded on CPU fallback.")

    def run(self, wav_path: Path) -> Tuple[str, list]:
        self._initialize_pipeline()
        result = LocalWhisperProvider._pipeline(
            str(wav_path),
            return_timestamps=True,
            generate_kwargs={"task": "transcribe", "language": "id"},
        )
        return result.get("text", ""), result.get("chunks", [])


# Pyannote Diarization

def _load_wav(wav_path: Path) -> dict:
    """Read the 16-bit PCM WAV from convert_to_wav into pyannote's waveform dict."""
    import wave

    with wave.open(str(wav_path), "rb") as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        frames = wf.readframes(wf.getnframes())
    samples = torch.frombuffer(bytearray(frames), dtype=torch.int16).float() / 32768.0
    waveform = samples.view(-1, channels).T.contiguous()   # (channel, time)
    return {"waveform": waveform, "sample_rate": sample_rate}


class PyannoteDiarization:
    """Lazy-loaded pyannote speaker diarization pipeline. Shared across all requests."""

    _pipeline = None

    def __init__(self) -> None:
        self._hf_token: str = os.getenv("HUGGINGFACE_TOKEN", "")
        self._device = torch.device("cuda" if _USE_CUDA else "cpu")
        self.enabled = bool(self._hf_token)

    def _initialize_pipeline(self) -> None:
        if PyannoteDiarization._pipeline is not None:
            return
        if not self.enabled:
            logger.warning(
                "HUGGINGFACE_TOKEN not set — diarization disabled. "
                "All segments will be labeled 'Speaker 1'."
            )
            return
        try:
            from pyannote.audio import Pipeline
            logger.info(f"Loading diarization model: {DIARIZATION_MODEL_ID}")
            login(token=self._hf_token, add_to_git_credential=False)
            PyannoteDiarization._pipeline = (
                Pipeline.from_pretrained(DIARIZATION_MODEL_ID).to(self._device)
            )
            logger.info("Pyannote diarization loaded successfully.")
        except Exception as exc:
            logger.warning(f"Pyannote failed to load: {exc}. Clearing cache and retrying...")
            cache_dir = Path(
                "/root/.cache/huggingface/hub/models--pyannote--speaker-diarization-3.1"
            )
            if cache_dir.exists():
                shutil.rmtree(cache_dir, ignore_errors=True)
                logger.warning("Pyannote cache cleared.")
            try:
                from pyannote.audio import Pipeline
                login(token=self._hf_token, add_to_git_credential=False)
                PyannoteDiarization._pipeline = (
                    Pipeline.from_pretrained(DIARIZATION_MODEL_ID).to(self._device)
                )
                logger.info("Pyannote loaded successfully on retry.")
            except Exception as exc2:
                logger.error(
                    f"Critical: Pyannote failed after cache clear: {exc2}\n"
                    "Ensure HUGGINGFACE_TOKEN is valid and model terms accepted at "
                    "https://hf.co/pyannote/speaker-diarization-3.1"
                )
                PyannoteDiarization._pipeline = None

    def diarize(self, wav_path: Path):
        """Run diarization on an already-converted WAV. Returns annotation or None."""
        self._initialize_pipeline()
        if PyannoteDiarization._pipeline is None:
            return None
        try:
            # Pass the waveform in memory: pyannote 4 reads files through
            # torchcodec, which is not usable in the container.
            return PyannoteDiarization._pipeline(_load_wav(wav_path))
        except Exception as exc:
            logger.error(f"Diarization inference failed: {exc}")
            return None


# Local Provider: Whisper-Small + Pyannote 3.1 

class WhisperSmallWithDiarizationProvider(TranscriptionProvider):
    """
    Whisper-small (ASR) + Pyannote 3.1 (speaker diarization).
    This is the sole local provider — Whisper-only is not exposed externally.
    """

    def __init__(self, diarizer: "PyannoteDiarization | None" = None) -> None:
        self.whisper  = LocalWhisperProvider()
        self.diarizer = diarizer or PyannoteDiarization()

    async def transcribe(
        self, audio_path: Path
    ) -> Tuple[List[TranscriptSegment], str, float]:
        wav_path    = await convert_to_wav(audio_path)
        cleanup_wav = wav_path != audio_path

        try:
            loop = asyncio.get_running_loop()

            full_text, whisper_chunks = await loop.run_in_executor(
                None, self.whisper.run, wav_path
            )
            diarization = await loop.run_in_executor(
                None, self.diarizer.diarize, wav_path
            )

            segments = self._align(whisper_chunks, diarization)
            duration = segments[-1].end_time if segments else 0.0
            return segments, full_text, duration
        finally:
            if cleanup_wav and wav_path.exists():
                wav_path.unlink(missing_ok=True)

    @staticmethod
    def _align(whisper_chunks: list, diarization) -> List[TranscriptSegment]:
        return align_chunks_with_speakers(whisper_chunks, diarization)


def align_chunks_with_speakers(whisper_chunks: list, diarization) -> List[TranscriptSegment]:
    """Assign speaker labels to Whisper chunks via maximum-overlap matching.
    Chunks: [{"text": str, "timestamp": (start, end)}]; diarization may be None."""

    def _fallback(chunks: list) -> List[TranscriptSegment]:
        return [
            TranscriptSegment(
                start_time=float((c.get("timestamp") or [0, 0])[0] or 0),
                end_time=float((c.get("timestamp") or [0, 0])[1] or 0),
                speaker="Speaker 1",
                text=c["text"].strip(),
            )
            for c in chunks if c.get("text", "").strip()
        ]

    if not diarization:
        return _fallback(whisper_chunks)

    # Normalise annotation wrapper (pyannote may wrap the result)
    if hasattr(diarization, "speaker_diarization"):
        diarization = diarization.speaker_diarization
    elif hasattr(diarization, "annotation"):
        diarization = diarization.annotation

    try:
        diar_turns = list(diarization.itertracks(yield_label=True))
    except Exception:
        return _fallback(whisper_chunks)

    segments: List[TranscriptSegment] = []
    for chunk in whisper_chunks:
        text = chunk.get("text", "").strip()
        if not text:
            continue
        ts      = chunk.get("timestamp") or (0, 0)
        c_start = float(ts[0] or 0)
        c_end   = float(ts[1] or 0)

        best_speaker, max_overlap = "Speaker 1", 0.0
        for turn, _, spk in diar_turns:
            overlap = min(c_end, turn.end) - max(c_start, turn.start)
            if overlap > max_overlap:
                max_overlap = overlap
                # Pyannote labels: SPEAKER_00 → Speaker 1, SPEAKER_01 → Speaker 2
                try:
                    spk_num = int(str(spk).split("_")[-1]) + 1
                except (ValueError, IndexError):
                    spk_num = 1
                best_speaker = f"Speaker {spk_num}"

        segments.append(
            TranscriptSegment(
                start_time=c_start,
                end_time=c_end,
                speaker=best_speaker,
                text=text,
            )
        )
    return segments


# Cloud Provider (Groq Whisper) 

GROQ_WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
GROQ_WHISPER_LANGUAGE = os.getenv("GROQ_WHISPER_LANGUAGE", "id")   # empty = auto-detect
_GROQ_CHUNK_SECONDS = 20 * 60        # 20 min of 16 kHz mono MP3 at 32 kbps is about 5 MB


async def _run(cmd: list) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {err.decode()[-500:]}")
    return out.decode()


async def _audio_duration(path: Path) -> float:
    out = await _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ])
    return float(out.strip() or 0)


class GroqWhisperProvider(TranscriptionProvider):
    """
    Whisper on the Groq API, optionally combined with local pyannote diarization.

    The free tier accepts files up to 25 MB, so the audio is re-encoded to
    compact MP3 and sent in 20-minute pieces; segment timestamps are shifted
    back by each piece's offset before alignment with the diarization turns.
    """

    def __init__(self, diarizer: "PyannoteDiarization", diarize: bool = True) -> None:
        self._diarizer = diarizer
        self._diarize = diarize
        self._client = None

    def _groq(self):
        if self._client is None:
            api_key = os.getenv("GROQ_API_KEY", "")
            if not api_key:
                raise ValueError("GROQ_API_KEY is not configured in backend/.env.")
            from groq import Groq
            self._client = Groq(api_key=api_key)
        return self._client

    def _transcribe_piece(self, mp3_path: Path, offset: float) -> list:
        kwargs = {"language": GROQ_WHISPER_LANGUAGE} if GROQ_WHISPER_LANGUAGE else {}
        with open(mp3_path, "rb") as f:
            resp = self._groq().audio.transcriptions.create(
                file=(mp3_path.name, f.read()),
                model=GROQ_WHISPER_MODEL,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
                temperature=0.0,
                **kwargs,
            )
        raw = getattr(resp, "segments", None)
        if raw is None and isinstance(resp, dict):
            raw = resp.get("segments")
        chunks = []
        for seg in raw or []:
            get = seg.get if isinstance(seg, dict) else (lambda k, _s=seg: getattr(_s, k, None))
            text = (get("text") or "").strip()
            if text:
                chunks.append({
                    "text": text,
                    "timestamp": (float(get("start") or 0) + offset,
                                  float(get("end") or 0) + offset),
                })
        return chunks

    async def transcribe(
        self, audio_path: Path
    ) -> Tuple[List[TranscriptSegment], str, float]:
        self._groq()  # fail fast when the key is missing
        wav_path = await convert_to_wav(audio_path)
        pieces: List[Path] = []
        try:
            loop = asyncio.get_running_loop()
            diar_task = None
            if self._diarize:
                diar_task = loop.run_in_executor(None, self._diarizer.diarize, wav_path)

            duration = await _audio_duration(wav_path)
            chunks: list = []
            start = 0.0
            idx = 0
            while start < max(duration, 0.1):
                piece = wav_path.with_name(f"{wav_path.stem}_part{idx:03d}.mp3")
                await _run([
                    "ffmpeg", "-y", "-ss", str(start), "-t", str(_GROQ_CHUNK_SECONDS),
                    "-i", str(wav_path), "-ac", "1", "-ar", "16000", "-b:a", "32k",
                    str(piece),
                ])
                pieces.append(piece)
                chunks += await loop.run_in_executor(
                    None, self._transcribe_piece, piece, start
                )
                start += _GROQ_CHUNK_SECONDS
                idx += 1

            diarization = await diar_task if diar_task is not None else None
            segments = align_chunks_with_speakers(chunks, diarization)
            full_text = " ".join(s.text for s in segments)
            return segments, full_text, duration or (segments[-1].end_time if segments else 0.0)
        finally:
            for p in pieces:
                p.unlink(missing_ok=True)
            if wav_path != audio_path:
                wav_path.unlink(missing_ok=True)


# Cloud Provider (Gemini 3.5 Transcribe) 

GEMINI_TRANSCRIBE_MODEL = os.getenv("GEMINI_TRANSCRIBE_MODEL", "gemini-3.5-transcribe")
GEMINI_TRANSCRIBE_LANGUAGE = os.getenv("GEMINI_TRANSCRIBE_LANGUAGE", "")  # empty = auto-detect; a wrong hint drops speech
_GEMINI_DIARIZATION_MAX_SECONDS = 30 * 60   # documented limit with diarization enabled
_SEGMENT_MAX_GAP = 1.2       # seconds of silence that closes a segment
_SEGMENT_MAX_WORDS = 45      # keep segments short enough to be good retrieval chunks


def _gemini_key() -> str:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""


def _offset_seconds(value) -> float:
    """Gemini offsets come as strings like '12.340s'; accept numbers too."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().rstrip("s")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _attr(obj, name):
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def words_to_segments(words: list) -> List[TranscriptSegment]:
    """
    Group word annotations {speaker, start_offset, end_offset, text} into segments.
    A new segment starts when the speaker changes, after a pause longer than
    _SEGMENT_MAX_GAP, or when a segment reaches _SEGMENT_MAX_WORDS and a
    sentence ends. Speaker ids such as 'spk_1' become 'Speaker 1'.
    """
    segments: List[TranscriptSegment] = []
    cur_words: List[str] = []
    cur_spk, cur_start, cur_end = None, 0.0, 0.0

    def label(raw) -> str:
        raw = str(raw or "")
        digits = "".join(ch for ch in raw if ch.isdigit())
        return f"Speaker {int(digits)}" if digits else (raw or "Speaker 1")

    def flush():
        if cur_words:
            text = " ".join(cur_words).replace(" ,", ",").replace(" .", ".").strip()
            if text:
                segments.append(TranscriptSegment(
                    start_time=cur_start, end_time=cur_end,
                    speaker=label(cur_spk), text=text,
                ))

    for w in words:
        text = str(_attr(w, "text") or "").strip()
        if not text:
            continue
        spk = _attr(w, "speaker")
        start = _offset_seconds(_attr(w, "start_offset"))
        end = _offset_seconds(_attr(w, "end_offset")) or start
        new_segment = (
            not cur_words
            or spk != cur_spk
            or start - cur_end > _SEGMENT_MAX_GAP
            or (len(cur_words) >= _SEGMENT_MAX_WORDS and cur_words[-1][-1:] in ".?!")
        )
        if new_segment:
            flush()
            cur_words, cur_spk, cur_start = [], spk, start
        cur_words.append(text)
        cur_end = max(end, start)
    flush()
    return segments


class GeminiTranscribeProvider(TranscriptionProvider):
    """
    Gemini 3.5 Transcribe with speaker diarization and word timestamps in a
    single API call, so nothing heavy runs locally. Free tier available; note
    that free-tier content may be used by Google to improve its products.
    """

    def __init__(self) -> None:
        self._client = None

    def _genai(self):
        if self._client is None:
            key = _gemini_key()
            if not key:
                raise ValueError("GEMINI_API_KEY is not configured in backend/.env.")
            from google import genai
            self._client = genai.Client(api_key=key)
        return self._client

    def _call(self, mp3_path: Path):
        client = self._genai()
        uploaded = client.files.upload(file=str(mp3_path))
        try:
            mode = {
                "type": "verbatim",
                "diarization_mode": "speaker",
                "timestamp_granularities": ["word"],
            }
            config = {"mode": mode}
            if GEMINI_TRANSCRIBE_LANGUAGE:
                config["language_codes"] = [GEMINI_TRANSCRIBE_LANGUAGE]
            return client.interactions.create(
                model=GEMINI_TRANSCRIBE_MODEL,
                input=[{
                    "type": "audio",
                    "uri": uploaded.uri,
                    "mime_type": getattr(uploaded, "mime_type", None) or "audio/mpeg",
                }],
                generation_config={"transcription_config": config},
            )
        finally:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass

    @staticmethod
    def _word_annotations(interaction) -> list:
        words = []
        for step in _attr(interaction, "steps") or []:
            for content in _attr(step, "content") or []:
                for ann in _attr(content, "annotations") or []:
                    if _attr(ann, "type") == "word_info":
                        words.append(ann)
        return words

    async def transcribe(
        self, audio_path: Path
    ) -> Tuple[List[TranscriptSegment], str, float]:
        self._genai()  # fail fast when the key is missing
        wav_path = await convert_to_wav(audio_path)
        mp3_path = wav_path.with_name(f"{wav_path.stem}_gemini.mp3")
        try:
            duration = await _audio_duration(wav_path)
            if duration > _GEMINI_DIARIZATION_MAX_SECONDS:
                raise ValueError(
                    f"Audio is {duration / 60:.1f} min; Gemini Transcribe with speaker "
                    "labels supports up to 30 min. Trim the file or use the groq provider."
                )
            await _run([
                "ffmpeg", "-y", "-i", str(wav_path), "-ac", "1", "-ar", "16000",
                "-b:a", "48k", str(mp3_path),
            ])
            loop = asyncio.get_running_loop()
            interaction = await loop.run_in_executor(None, self._call, mp3_path)

            segments = words_to_segments(self._word_annotations(interaction))
            full_text = (_attr(interaction, "output_text") or "").strip()
            if not segments and full_text:
                segments = [TranscriptSegment(start_time=0.0, end_time=duration,
                                              speaker="Speaker 1", text=full_text)]
            if not full_text:
                full_text = " ".join(s.text for s in segments)
            return segments, full_text, duration
        finally:
            mp3_path.unlink(missing_ok=True)
            if wav_path != audio_path:
                wav_path.unlink(missing_ok=True)


# Orchestrator 

class TranscriptionOrchestrator:
    """
    Routes provider names to providers (all created lazily on first use):

    "local"      -> Whisper (local) + Pyannote 3.1
    "groq"       -> Groq Whisper + Pyannote 3.1 (Speaker 1 only if no HF token)
    "groq_fast"  -> Groq Whisper, no diarization
    "gemini"     -> Gemini 3.5 Transcribe (transcription + speaker labels)
    """

    PROVIDERS = ("gemini", "groq", "groq_fast", "local")

    def __init__(self) -> None:
        self._diarizer = PyannoteDiarization()
        self._instances: dict = {}

    def _get(self, provider: str) -> TranscriptionProvider:
        if provider not in self._instances:
            if provider == "gemini":
                self._instances[provider] = GeminiTranscribeProvider()
            elif provider == "groq":
                self._instances[provider] = GroqWhisperProvider(self._diarizer, diarize=True)
            elif provider == "groq_fast":
                self._instances[provider] = GroqWhisperProvider(self._diarizer, diarize=False)
            else:
                self._instances[provider] = WhisperSmallWithDiarizationProvider(self._diarizer)
        return self._instances[provider]

    async def transcribe(
        self, audio_path: Path, provider: str = "local"
    ) -> Tuple[List[TranscriptSegment], str, float]:
        if provider not in self.PROVIDERS:
            raise ValueError(f"Unknown provider '{provider}'. Use one of {self.PROVIDERS}.")
        return await self._get(provider).transcribe(audio_path)

    @staticmethod
    def availability() -> dict:
        """Which providers are usable with the current backend/.env."""
        groq = bool(os.getenv("GROQ_API_KEY"))
        hf = bool(os.getenv("HUGGINGFACE_TOKEN"))
        gemini = bool(_gemini_key())
        return {
            "gemini": {"ready": gemini, "speaker_labels": True,
                       "note": "" if gemini else "GEMINI_API_KEY belum diisi"},
            "groq": {"ready": groq, "speaker_labels": hf,
                     "note": "" if groq else "GROQ_API_KEY belum diisi"},
            "groq_fast": {"ready": groq, "speaker_labels": False,
                          "note": "" if groq else "GROQ_API_KEY belum diisi"},
            "local": {"ready": True, "speaker_labels": hf,
                      "note": "berat di CPU (model Whisper lokal)"},
        }


transcription_service = TranscriptionOrchestrator()
