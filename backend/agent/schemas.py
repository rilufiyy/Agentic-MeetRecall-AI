"""Pydantic models for tool arguments. The JSON schema sent to the LLM is generated from these."""
from __future__ import annotations

import re
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

JenisPoin = Literal["action_items", "keputusan", "isu_terbuka", "ringkasan", "semua"]


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CariTranskripArgs(_Args):
    meeting_id: str = Field(..., min_length=1, max_length=64, description="ID meeting yang sedang dibahas.")
    query: str = Field(..., min_length=3, max_length=300,
                       description="Kata kunci atau pertanyaan untuk dicari di transkrip.")
    top_k: int = Field(5, ge=1, le=8, description="Jumlah potongan transkrip yang dikembalikan.")


class EkstrakPoinArgs(_Args):
    meeting_id: str = Field(..., min_length=1, max_length=64)
    jenis: JenisPoin = Field(..., description=(
        "semua = keempat jenis di bawah sekaligus (pakai ini sebelum membuat laporan); "
        "action_items = tugas tindak lanjut; keputusan = hal yang disepakati; "
        "isu_terbuka = masalah atau pertanyaan yang belum selesai; ringkasan = poin utama meeting."))
    fokus: Optional[str] = Field(None, max_length=100, description=(
        "Opsional. Penyempit pencarian, misalnya nama speaker atau topik yang diminta user."))


class StatistikMeetingArgs(_Args):
    meeting_id: str = Field(..., min_length=1, max_length=64)
    rekap_id: Optional[str] = Field(None, max_length=64, description=(
        "Opsional. rekap_id dari ekstrak_poin_meeting untuk menghitung action items per orang."))


def _rekap_id_field():
    return Field(..., min_length=1, max_length=64, description=(
        "rekap_id yang dikembalikan ekstrak_poin_meeting (12 karakter huruf dan angka). "
        "BUKAN meeting_id. Bila belum ada rekap, panggil ekstrak_poin_meeting dulu."))


AlasanKlarifikasi = Literal["penanggung_jawab_ambigu", "tenggat_ambigu", "informasi_tidak_ditemukan",
                            "kualitas_transkrip", "permintaan_tidak_jelas", "lainnya"]


class BuatTaskArgs(_Args):
    rekap_id: str = _rekap_id_field()
    item_ids: List[str] = Field(..., min_length=1, max_length=20, description=(
        "ID action item dari rekap, misalnya ['A1', 'A3']. Hanya item action_items."))

    @field_validator("item_ids")
    @classmethod
    def _ids(cls, v: List[str]) -> List[str]:
        bad = [i for i in v if not re.fullmatch(r"A\d{1,3}", i)]
        if bad:
            raise ValueError(f"item_ids harus berformat A<nomor>, tidak valid: {bad}")
        return list(dict.fromkeys(v))


def _unique(values: List[str]) -> List[str]:
    return list(dict.fromkeys(values))


class EksporLaporanArgs(_Args):
    rekap_id: str = _rekap_id_field()
    formats: List[Literal["pdf", "docx", "md", "srt"]] = Field(..., min_length=1, max_length=4, description=(
        "Satu atau lebih format. pdf = dokumen siap cetak; docx = Microsoft Word; md = Markdown; "
        "srt = subtitle transkrip dengan timestamp (bukan rekap). Bila user menyebut dua format "
        "(misalnya PDF dan Word), isi keduanya dalam satu panggilan: ['pdf', 'docx']."))

    @field_validator("formats")
    @classmethod
    def _dedupe(cls, v: List[str]) -> List[str]:
        return _unique(v)
    izinkan_bagian_kosong: bool = Field(False, description=(
        "False (default): laporan pdf, docx, md ditolak bila ada bagian yang belum dianalisis; panggil "
        "ekstrak_poin_meeting jenis 'semua' dulu. True hanya bila user sengaja meminta laporan sebagian."))
    sertakan_transkrip: bool = Field(True, description=(
        "True (default): laporan pdf, docx, dan md memuat transkrip lengkap dengan pembicara dan timestamp "
        "di bagian akhir. Isi False hanya bila user meminta laporan tanpa transkrip."))


class KirimEmailRekapArgs(_Args):
    # No recipient, address, subject or path argument: all of them are fixed by code.
    rekap_id: str = _rekap_id_field()
    formats: List[Literal["pdf", "docx", "md"]] = Field(
        default_factory=lambda: ["pdf"], min_length=1, max_length=3,
        description=("Format lampiran, satu atau lebih; default ['pdf']. Bila user meminta PDF dan Word, "
                     "isi ['pdf', 'docx']. Setiap format harus sudah dibuat dengan ekspor_laporan."))

    @field_validator("formats")
    @classmethod
    def _dedupe(cls, v: List[str]) -> List[str]:
        return _unique(v)


class MintaKlarifikasiArgs(_Args):
    alasan: AlasanKlarifikasi
    pertanyaan: str = Field(..., min_length=5, max_length=300,
                            description="Pertanyaan singkat untuk user, dalam bahasa user.")
    item_ids: List[str] = Field(default_factory=list, max_length=20,
                                description="Opsional. ID item rekap yang ditanyakan.")


def tool_schema(model: type[BaseModel]) -> dict:
    """JSON schema for the tools parameter, without pydantic's title fields."""
    def clean(node):
        if isinstance(node, dict):
            return {k: clean(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [clean(v) for v in node]
        return node
    return clean(model.model_json_schema())
