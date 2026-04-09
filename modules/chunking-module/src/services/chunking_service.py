import json

import boto3

from src.utils.logger import get_logger

logger = get_logger(__name__)

TARGET_CHUNK_WORDS = 500
OVERLAP_WORDS = 50


class ChunkingService:
    def __init__(self, s3_client=None, sqs_client=None):
        self.s3_client = s3_client or boto3.client("s3")
        self.sqs_client = sqs_client or boto3.client("sqs")

    def read_transcript(self, bucket, key):
        response = self.s3_client.get_object(Bucket=bucket, Key=key)
        return json.loads(response["Body"].read())

    def summarize_chunks(self, chunks):
        raise NotImplementedError

    def parse_timed_words(self, transcript):
        timed_words = []
        for item in transcript["results"]["items"]:
            alt = item["alternatives"][0]
            if item["type"] == "pronunciation":
                timed_words.append({
                    "text": alt["content"],
                    "start_time": float(item["start_time"]),
                    "end_time": float(item["end_time"]),
                })
            elif item["type"] == "punctuation" and timed_words:
                timed_words[-1]["text"] += alt["content"]
        return timed_words

    def build_sentences(self, timed_words):
        if not timed_words:
            return []

        sentences = []
        current_words = []

        for word in timed_words:
            current_words.append(word)
            if word["text"].endswith((".", "!", "?")):
                sentences.append({
                    "text": " ".join(w["text"] for w in current_words),
                    "start_time": current_words[0]["start_time"],
                    "end_time": current_words[-1]["end_time"],
                    "word_count": len(current_words),
                })
                current_words = []

        if current_words:
            sentences.append({
                "text": " ".join(w["text"] for w in current_words),
                "start_time": current_words[0]["start_time"],
                "end_time": current_words[-1]["end_time"],
                "word_count": len(current_words),
            })

        return sentences

    def chunk(self, timed_words, video_id, source_key, speaker, title):
        sentences = self.build_sentences(timed_words)
        if not sentences:
            return []

        raw_chunks = []
        current_sentences = []
        current_word_count = 0

        for sentence in sentences:
            if (current_word_count + sentence["word_count"] > TARGET_CHUNK_WORDS
                    and current_sentences):
                raw_chunks.append(current_sentences)
                overlap_sentences = self._get_overlap_sentences(current_sentences)
                current_sentences = list(overlap_sentences)
                current_word_count = sum(s["word_count"] for s in current_sentences)

            current_sentences.append(sentence)
            current_word_count += sentence["word_count"]

        if current_sentences:
            raw_chunks.append(current_sentences)

        total_chunks = len(raw_chunks)
        chunks = []
        for i, chunk_sentences in enumerate(raw_chunks, start=1):
            text = " ".join(s["text"] for s in chunk_sentences)
            word_count = sum(s["word_count"] for s in chunk_sentences)
            chunks.append({
                "chunk_id": f"{video_id}-chunk-{i:03d}",
                "video_id": video_id,
                "sequence": i,
                "text": text,
                "word_count": word_count,
                "start_time": chunk_sentences[0]["start_time"],
                "end_time": chunk_sentences[-1]["end_time"],
                "metadata": {
                    "speaker": speaker,
                    "title": title,
                    "source_s3_key": source_key,
                    "total_chunks": total_chunks,
                },
            })

        return chunks

    def _get_overlap_sentences(self, sentences):
        overlap = []
        word_count = 0
        for sentence in reversed(sentences):
            overlap.insert(0, sentence)
            word_count += sentence["word_count"]
            if word_count >= OVERLAP_WORDS:
                break
        return overlap

    def store_chunks(self, bucket, video_id, chunks):
        keys = []
        for chunk in chunks:
            key = f"chunks/{video_id}/chunk-{chunk['sequence']:03d}.json"
            self.s3_client.put_object(
                Bucket=bucket,
                Key=key,
                Body=json.dumps(chunk),
                ContentType="application/json",
            )
            keys.append(key)
        return keys

    def publish_chunks(self, queue_url, chunk_keys, bucket, video_id, speaker, title):
        for key in chunk_keys:
            message_body = json.dumps({
                "chunk_s3_key": key,
                "bucket": bucket,
                "video_id": video_id,
                "speaker": speaker,
                "title": title,
            })
            self.sqs_client.send_message(
                QueueUrl=queue_url,
                MessageBody=message_body,
            )
        return len(chunk_keys)


service = ChunkingService()
