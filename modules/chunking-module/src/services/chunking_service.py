import json

import boto3

from src.utils.logger import get_logger

logger = get_logger(__name__)

TARGET_CHUNK_WORDS = 500
OVERLAP_WORDS = 50
SENTENCE_ENDINGS = frozenset((".", "!", "?"))


class ChunkingService:
    def __init__(self) -> None:
        self._s3 = boto3.client("s3")

    def read_transcript(self, bucket: str, key: str) -> dict:
        response = self._s3.get_object(Bucket=bucket, Key=key)
        return json.loads(response["Body"].read())

    def parse_timed_words(self, transcript: dict) -> list[dict]:
        items = transcript["results"]["items"]
        timed_words: list[dict] = []

        for item in items:
            content = item["alternatives"][0]["content"]
            if item["type"] == "pronunciation":
                timed_words.append({
                    "text": content,
                    "start_time": float(item["start_time"]),
                    "end_time": float(item["end_time"]),
                })
            elif item["type"] == "punctuation" and timed_words:
                timed_words[-1]["text"] += content

        return timed_words

    def build_sentences(self, timed_words: list[dict]) -> list[dict]:
        if not timed_words:
            return []

        sentences: list[dict] = []
        current_words: list[dict] = []

        for word in timed_words:
            current_words.append(word)
            if word["text"][-1] in SENTENCE_ENDINGS:
                sentences.append(self._finalize_sentence(current_words))
                current_words = []

        if current_words:
            sentences.append(self._finalize_sentence(current_words))

        return sentences

    def _finalize_sentence(self, words: list[dict]) -> dict:
        return {
            "text": " ".join(w["text"] for w in words),
            "start_time": words[0]["start_time"],
            "end_time": words[-1]["end_time"],
            "word_count": len(words),
            "words": list(words),
        }

    def chunk(
        self,
        timed_words: list[dict],
        video_id: str,
        source_key: str,
    ) -> list[dict]:
        sentences = self.build_sentences(timed_words)
        if not sentences:
            return []

        chunks: list[dict] = []
        current_sentences: list[dict] = []
        current_word_count = 0
        prev_chunk_sentences: list[dict] = []
        sequence = 1

        for sentence in sentences:
            if (
                current_word_count + sentence["word_count"] > TARGET_CHUNK_WORDS
                and current_sentences
            ):
                chunks.append(
                    self._build_chunk_dict(
                        current_sentences, sequence, video_id, source_key
                    )
                )
                sequence += 1
                prev_chunk_sentences = list(current_sentences)

                overlap_sentences = self._get_overlap_sentences(prev_chunk_sentences)
                overlap_word_count = sum(s["word_count"] for s in overlap_sentences)

                current_sentences = overlap_sentences + [sentence]
                current_word_count = overlap_word_count + sentence["word_count"]
            else:
                current_sentences.append(sentence)
                current_word_count += sentence["word_count"]

        if current_sentences:
            chunks.append(
                self._build_chunk_dict(
                    current_sentences, sequence, video_id, source_key
                )
            )

        for c in chunks:
            c["metadata"]["total_chunks"] = len(chunks)

        return chunks

    def _get_overlap_sentences(self, sentences: list[dict]) -> list[dict]:
        overlap: list[dict] = []
        word_count = 0

        for sentence in reversed(sentences):
            if word_count + sentence["word_count"] > OVERLAP_WORDS and overlap:
                break
            overlap.insert(0, sentence)
            word_count += sentence["word_count"]

        return overlap

    def _build_chunk_dict(
        self,
        sentences: list[dict],
        sequence: int,
        video_id: str,
        source_key: str,
    ) -> dict:
        return {
            "chunk_id": f"{video_id}-chunk-{sequence:03d}",
            "video_id": video_id,
            "sequence": sequence,
            "text": " ".join(s["text"] for s in sentences),
            "word_count": sum(s["word_count"] for s in sentences),
            "start_time": sentences[0]["start_time"],
            "end_time": sentences[-1]["end_time"],
            "metadata": {
                "source_s3_key": source_key,
                "total_chunks": 0,
            },
        }

    def store_chunks(
        self, bucket: str, video_id: str, chunks: list[dict]
    ) -> list[str]:
        keys: list[str] = []

        for chunk in chunks:
            key = f"chunks/{video_id}/chunk-{chunk['sequence']:03d}.json"
            self._s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=json.dumps(chunk),
                ContentType="application/json",
            )
            keys.append(key)

        logger.info(
            "stored %d chunks for video %s in s3://%s/chunks/%s/",
            len(chunks),
            video_id,
            bucket,
            video_id,
        )

        return keys
