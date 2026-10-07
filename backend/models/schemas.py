from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# Transcript 

class TranscriptSegment(BaseModel):
    start_time: float
    end_time: float
    speaker: str
    text: str


class TranscriptionResult(BaseModel):
    meeting_id: str
    filename: str
    duration: float
    segments: List[TranscriptSegment]
    full_text: str
    provider: str = "local"          
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "completed"


class SpeakerUpdate(BaseModel):
    """New speaker label for every segment, in transcript order."""
    speakers: List[str] = Field(..., min_length=1)
    expected_speakers: Optional[List[str]] = Field(
        default=None,
        description="Labels the edit was based on; the update is rejected (409) when "
                    "the stored labels changed since, e.g. a second tab or a repeated submit.",
    )


# Meeting Index

class MeetingInfo(BaseModel):
    meeting_id: str
    filename: str
    duration: float
    provider: str = "local"
    created_at: datetime
    status: str                     
    num_speakers: int = 0
    num_segments: int = 0


# RAG 

class ChatTurn(BaseModel):
    """One Q&A turn for conversation memory (last N turns sent by client)."""
    question: str
    answer: str


RetrievalMode = Literal["vector", "fulltext", "hybrid"]
FusionMethod = Literal["rrf", "weighted"]


class RetrievalSettings(BaseModel):
    """Knobs shared by chat, retrieval comparison, and evaluation."""
    retrieval_mode: RetrievalMode = Field(
        default="hybrid",
        description="vector = FAISS cosine, fulltext = BM25, hybrid = both fused.",
    )
    fusion: FusionMethod = Field(default="rrf", description="Hybrid fusion method.")
    rrf_k: int = Field(default=60, ge=1, le=1000)
    alpha: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="Weighted fusion only: weight of the vector score (1 - alpha for BM25).",
    )
    candidate_k: int = Field(default=20, ge=1, le=200)
    rerank: bool = Field(default=False, description="Second-stage cross-encoder reranking.")
    min_score: float = Field(
        default=0.40, ge=0.0, le=1.0,
        description="Abstain when best cosine similarity is below this (0 = off; 0.40 tuned on the sample eval set).",
    )
    expand_neighbors: int = Field(
        default=0, ge=0, le=3,
        description="Attach N neighbouring segments to each hit as LLM context.",
    )

    def to_config_kwargs(self) -> Dict:
        return {
            "mode": self.retrieval_mode, "fusion": self.fusion, "rrf_k": self.rrf_k,
            "alpha": self.alpha, "candidate_k": self.candidate_k, "rerank": self.rerank,
            "min_score": self.min_score, "expand_neighbors": self.expand_neighbors,
        }


class RAGChatRequest(RetrievalSettings):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)
    history: List[ChatTurn] = Field(
        default=[],
        description="Last N conversation turns for contextual follow-up questions.",
    )


class SourceChunk(BaseModel):
    text: str
    speaker: str
    start_time: float
    end_time: float
    score: float
    chunk_id: Optional[int] = None
    rank: Optional[int] = None
    retrieval_mode: Optional[str] = None
    vector_score: Optional[float] = None
    keyword_score: Optional[float] = None
    rerank_score: Optional[float] = None
    matched_terms: List[str] = []


class RAGChatResponse(BaseModel):
    """Structured meeting intelligence response (pure JSON, no HTML)."""
    meeting_id: str
    transcription_summary: str   
    key_actions: List[str]       
    keywords: List[str]          
    sources: List[SourceChunk]   
    retrieval_mode: str = "vector"
    abstained: bool = False
    abstain_reason: str = ""
    reranked: bool = False
    retrieval_latency_ms: float = 0.0
    retrieval_query: str = ""    # query sent to retrieval (follow-ups are rewritten)


# Retrieval comparison and evaluation

class RetrieveRequest(RetrievalSettings):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    modes: List[RetrievalMode] = Field(default=["fulltext", "vector", "hybrid"])


class ModeResult(BaseModel):
    mode: str
    chunks: List[SourceChunk]
    abstained: bool = False
    abstain_reason: str = ""
    reranked: bool = False
    latency_ms: float = 0.0


class RetrieveResponse(BaseModel):
    meeting_id: str
    query: str
    results: List[ModeResult]


class EvalCase(BaseModel):
    id: str = ""
    query: str
    category: str = "umum"
    relevant_text_contains: List[str] = []
    relevant_chunk_ids: List[int] = []
    expect_no_answer: bool = False


class EvaluateRequest(RetrievalSettings):
    cases: List[EvalCase] = Field(..., min_length=1)
    k: int = Field(default=3, ge=1, le=20)
    modes: List[RetrievalMode] = Field(default=["fulltext", "vector", "hybrid"])


