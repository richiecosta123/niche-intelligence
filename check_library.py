import youtube_transcript_api
from youtube_transcript_api import YouTubeTranscriptApi

print(f"Library version: {youtube_transcript_api.__version__}")
print(f"\nAvailable methods:")
for method in dir(YouTubeTranscriptApi):
    if not method.startswith('_'):
        print(f"  - {method}")
