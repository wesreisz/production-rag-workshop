VIDEO_KNOWLEDGE_OVERVIEW = """# Video Knowledge Base

This MCP server connects to a video transcript knowledge base containing information from conference talks and presentations.

The knowledge base includes:

- **Transcript chunks**: Searchable text segments from video transcriptions
- **Speaker metadata**: Who presented each talk
- **Title metadata**: The title of each presentation
- **Timestamps**: Start and end times for each chunk within the original video

## Using the Knowledge Base

You can query this knowledge base by asking natural language questions. The system embeds your question, performs cosine similarity search against stored transcript chunks, and returns the most relevant results ranked by similarity score.

Available tools:
- **ask_video_question**: Ask any question about video content
- **list_indexed_videos**: See all videos in the knowledge base
- **search_by_speaker**: Search content from a specific speaker
"""

EXAMPLE_QUESTIONS = """# Example Questions

Here are examples of questions you can ask the video knowledge base:

## Speaker-Focused
- "What did Wesley Reisz talk about?"
- "What topics did [Speaker Name] cover?"
- "Who spoke about RAG pipelines?"

## Topic-Focused
- "What was discussed about error handling?"
- "What sessions covered vector databases?"
- "Tell me about embedding strategies mentioned in the talks"

## General
- "What were the main themes across all talks?"
- "What best practices were recommended?"
- "What tools and technologies were mentioned?"

## Specific
- "What examples were given for chunking strategies?"
- "What were the key takeaways about production systems?"

Feel free to ask follow-up questions to dive deeper into any topic.
"""

FORMATTING_GUIDANCE = """# Tips for Better Questions

## Do's
- **Be specific**: Mention speaker names, topics, or concepts when you know them
- **Ask one thing at a time**: Focused questions get more targeted answers
- **Use natural language**: Write questions as you would ask a colleague
- **Ask for details**: Request examples, best practices, or specific insights

## Don'ts
- Avoid overly broad questions like "Tell me everything"
- Don't combine multiple unrelated questions in one query
- Skip jargon about the query system itself

## Getting Better Results
The more specific your question, the more targeted the answer. If you get a broad response, try narrowing to a specific speaker, topic, or aspect.
"""

__all__ = ["VIDEO_KNOWLEDGE_OVERVIEW", "EXAMPLE_QUESTIONS", "FORMATTING_GUIDANCE"]
