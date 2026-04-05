VIDEO_KNOWLEDGE_OVERVIEW = """
You have access to a video knowledge base containing indexed transcripts from conference talks and technical presentations.

Use the available tools to answer questions about video content:
- Use `list_indexed_videos` first to discover what videos are available.
- Use `ask_video_question` to search across all videos with a natural language question.
- Use `search_by_speaker` when the user wants to find content from a specific speaker.

Results include the transcript text, similarity score, speaker name, video title, and timestamp range so you can cite specific moments in the video.
""".strip()

EXAMPLE_QUESTIONS = """
Here are example questions you can ask about the video knowledge base:

- "What is retrieval-augmented generation?"
- "How does pgvector work for similarity search?"
- "What are the best practices for chunking documents?"
- "What did the speakers say about embedding models?"
- "What is the difference between RAG and fine-tuning?"

Try asking specific technical questions to get the most relevant transcript chunks.
""".strip()

FORMATTING_GUIDANCE = """
Tips for writing effective questions:

- Be specific: "How does Aurora pgvector handle cosine similarity?" gets better results than "tell me about databases".
- Include domain terms: use technical vocabulary from the topic area.
- For speaker-specific queries, use `search_by_speaker` with the exact speaker name from `list_indexed_videos`.
- Adjust `top_k` (default 5) to get more or fewer results — use a higher value for broad topics.
- Combine results from multiple queries to build a comprehensive answer.
""".strip()
