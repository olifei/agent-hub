# YouBuddy Agent

## Overview

YouBuddy is an AI-powered YouTube video analysis agent that extracts actionable insights from video content, comments, and channel performance data. In the retail marketing workflow, it bridges trend discovery and content creation by analyzing how trends manifest in video content and what resonates with audiences.

## Key Features

- **Video Content Analysis**: Analyzes video titles, descriptions, thumbnails, and transcripts to extract key topics and messaging patterns
- **Comment Sentiment Mining**: Processes viewer comments to gauge audience reception and identify unmet needs
- **Competitor Channel Tracking**: Monitors competitor YouTube channels for content strategy patterns
- **Performance Benchmarking**: Compares engagement metrics (views, likes, comments, shares) across similar content
- **Content Gap Detection**: Identifies trending topics with high search volume but low content supply

## How It Works

```
YouTube Data API → Video Collection → Content Analysis → Audience Insights → Strategy Report
                                           │
                                    Transcript Analysis
                                    Comment Sentiment
                                    Engagement Metrics
```

### Input
- Topic keywords or trend data (from Trendspotting Agent)
- Target audience demographics
- Competitor channel URLs (optional)

### Output
- Content performance analysis with engagement benchmarks
- Audience sentiment breakdown by topic
- Recommended content angles and formats
- Optimal posting schedule based on audience activity
- Hashtag and keyword recommendations

## Architecture

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Data Collector | YouTube Data API v3 | Fetch videos, channels, comments |
| Transcript Analyzer | Gemini | Extract topics from video transcripts |
| Sentiment Engine | Gemini | Analyze comment sentiment at scale |
| Trend Correlator | Custom | Match YouTube trends with market trends |

## Integration

YouBuddy receives trend data from **Trendspotting Agent** and feeds analyzed insights to **Creative Agent**:

```
Trendspotting → YouBuddy → Creative → SmartCat → Publish
                   ↑
            YouTube Data API
```

## Example Usage

```
User: Analyze top-performing YouTube content about sustainable fashion

Agent: Analysis of 500+ videos in the past 30 days:

📊 Content Performance Summary:
- Average views: 45K (top 10%: 280K+)
- Best performing format: "Day in my life" vlogs (3.2x avg engagement)
- Peak posting time: Tuesday/Thursday 2-4 PM

🎯 Top Content Angles:
1. "Thrift Haul" videos — 89% positive sentiment, high save rate
2. Brand comparison reviews — drives purchase intent
3. DIY upcycling tutorials — highest share rate

💡 Recommendations:
- Focus on authentic storytelling over polished production
- Include price comparisons for budget-conscious audience
- Leverage "before/after" thumbnail format (2.1x CTR)
```

## Status

> **Coming Soon** — This agent is currently under development. The code will be available once the implementation is complete.
