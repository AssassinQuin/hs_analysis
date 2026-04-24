# Search Strategies Reference

Detailed guidance on using available MCP search tools effectively.

## Tool Decision Matrix

### exa_web_search
- **Best for**: Semantic/natural language queries, academic papers, blog posts
- **Strength**: High-quality semantic matching, finds conceptually related content
- **Limitation**: May miss very recent content
- **Usage tip**: Write queries as descriptions of the ideal page, not keywords
- **Example**: `"MCTS UCT algorithm implementation for card games with incomplete information"`

### searxng_web_search
- **Best for**: Broad coverage, diverse sources, recent content
- **Strength**: Multiple search engine aggregation
- **Limitation**: Less semantic understanding
- **Usage tip**: Use specific keywords, can filter by category (general, images, news)
- **Example**: `query="MCTS Hearthstone AI implementation"`, `categories=["general"]`

### web-search-prime
- **Best for**: Chinese-language content, regional results
- **Strength**: Better CN region coverage, content_size parameter for depth
- **Usage tip**: Set `location="cn"` for Chinese content, `content_size="high"` for comprehensive answers
- **Example**: `search_query="蒙特卡洛树搜索 炉石传说 AI 算法实现"`

### zread_search_doc / zread_read_file
- **Best for**: Reading specific GitHub repository documentation
- **Strength**: Direct access to repo docs, README, wikis
- **Usage tip**: Use `repo_name="owner/repo"` format
- **Example**: Search for MCTS implementations in game AI repos

### github_search_code
- **Best for**: Finding specific code patterns across GitHub
- **Strength**: Searches actual code content, language filters
- **Usage tip**: Use `language:python` filter, `repo:` for specific repos
- **Example**: `query="MCTS UCT language:python game"`

### github_search_repositories
- **Best for**: Discovering relevant open-source projects
- **Strength**: Stars, activity metrics, topic tags
- **Example**: `query="MCTS game AI language:python stars:>10"`

### exa_web_fetch / webfetch
- **Best for**: Reading full content from known URLs
- **Usage**: Always follow up on promising search results to get full content
- **Tip**: Batch URLs when possible for efficiency

## Search Query Templates

### Algorithm Research
```
"{algorithm_name} implementation {domain} {language}"
"{algorithm_name} vs {alternative} comparison benchmark"
"{algorithm_name} {specific_aspect} optimization"
```

### Architecture Research
```
"{pattern_name} architecture {domain} best practices"
"{framework} {feature} design pattern"
"{system_type} {component} design considerations"
```

### Chinese-English Bilingual Search
Search both languages for comprehensive coverage:
- EN: `"MCTS UCT algorithm card game implementation"`
- CN: `"蒙特卡洛树搜索 卡牌游戏 算法实现"`

## Verification Strategy

For critical claims:
1. Find claim in Source A
2. Search for the same claim with different query
3. If Source B confirms → high confidence, cite both
4. If only Source A → medium confidence, note as "单一来源"
5. If contradictory → note conflict, seek authoritative source
