from tavily import TavilyClient
from src import config

client = TavilyClient(api_key=config.TAVILY_API_KEY)


def gather_reference(keywords: str, max_results: int = None) -> list[dict]:
    """Search the web and return clean reference snippets for grounding."""
    if max_results is None:
        max_results = config.SEARCH_MAX_RESULTS

    response = client.search(
        query=keywords,
        max_results=max_results,
        search_depth="advanced",
    )

    results = []
    for item in response.get("results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": item.get("content", ""),
        })
    return results


def format_for_prompt(results: list[dict]) -> str:
    """Turn reference snippets into a compact block to feed the generator."""
    blocks = []
    for i, r in enumerate(results, 1):
        blocks.append(f"[Source {i}] {r['title']}\n{r['content']}")
    return "\n\n".join(blocks)


if __name__ == "__main__":
    refs = gather_reference(
        "class 8 maths olympiad syllabus topics number theory geometry"
    )
    for r in refs:
        print("-", r["title"], "\n ", r["url"])
    print("\n--- formatted for prompt (first 800 chars) ---\n")
    print(format_for_prompt(refs)[:800])