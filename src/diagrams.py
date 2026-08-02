import os
import matplotlib
matplotlib.use("Agg")           # non-interactive backend (no display needed)
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from src import config
import math


import json
from groq import Groq
from src import config

_client = Groq(api_key=config.GROQ_API_KEY)



def draw_food_chain(items: list[str], output_path: str) -> str:
    """Draw a food-chain diagram (boxes + arrows) as a PNG. Boxes auto-size to
    fit their labels so long names don't overflow onto the arrows."""
    n = len(items)
    # Size each box to its label: width grows with the longest text
    longest = max(len(str(x)) for x in items)
    box_w = max(1.8, longest * 0.16)      # wider box for longer labels
    box_h = 0.9
    gap = 0.7                              # space between boxes (for the arrow)
    step = box_w + gap

    fig_width = max(6, n * step + 0.5)
    fig, ax = plt.subplots(figsize=(fig_width, 1.8))
    ax.set_xlim(0, n * step)
    ax.set_ylim(0, 1.6)
    ax.axis("off")

    y = 0.35
    for i, label in enumerate(items):
        x = i * step + 0.1
        box = patches.FancyBboxPatch(
            (x, y), box_w, box_h,
            boxstyle="round,pad=0.02", linewidth=1.5,
            edgecolor="#2c3e50", facecolor="#eaf2f8",
        )
        ax.add_patch(box)
        ax.text(x + box_w / 2, y + box_h / 2, label,
                ha="center", va="center", fontsize=10)
        # arrow in the GAP between this box and the next (no overlap)
        if i < n - 1:
            ax.annotate(
                "", xy=(x + box_w + gap - 0.05, y + box_h / 2),
                xytext=(x + box_w + 0.05, y + box_h / 2),
                arrowprops=dict(arrowstyle="->", lw=1.5, color="#2c3e50"),
            )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def draw_cycle(items: list[str], output_path: str) -> str:
    """Draw a cycle diagram (labeled nodes arranged in a circle with arrows
    flowing around). For water cycle, life cycle, etc. 'items' is ordered."""
    n = len(items)
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.set_xlim(-1.6, 1.6)
    ax.set_ylim(-1.6, 1.6)
    ax.axis("off")
    ax.set_aspect("equal")

    radius = 1.1
    positions = []
    for i in range(n):
        # place nodes evenly around a circle, starting from the top
        angle = math.pi / 2 - (2 * math.pi * i / n)
        x, y = radius * math.cos(angle), radius * math.sin(angle)
        positions.append((x, y))

    # draw each node
    for (x, y), label in zip(positions, items):
        circle = patches.Circle((x, y), 0.32, linewidth=1.5,
                                 edgecolor="#2c3e50", facecolor="#eaf2f8")
        ax.add_patch(circle)
        ax.text(x, y, label, ha="center", va="center", fontsize=9, wrap=True)

    # draw curved arrows connecting each node to the next (looping back)
    for i in range(n):
        x1, y1 = positions[i]
        x2, y2 = positions[(i + 1) % n]
        ax.annotate("", xy=(x2 * 0.72, y2 * 0.72), xytext=(x1 * 0.72, y1 * 0.72),
                    arrowprops=dict(arrowstyle="->", lw=1.4, color="#2c3e50",
                                    connectionstyle="arc3,rad=0.25"))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def draw_blank_space(label: str, output_path: str) -> str:
    """For complex diagrams we can't draw accurately: render a clean bordered
    box that says 'draw/label here', like a real printed exam's diagram space."""
    fig, ax = plt.subplots(figsize=(6, 3.2))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 5)
    ax.axis("off")

    box = patches.FancyBboxPatch((0.3, 0.3), 9.4, 4.4,
                                 boxstyle="round,pad=0.02", linewidth=1.3,
                                 edgecolor="#888888", facecolor="#fbfbfb",
                                 linestyle="--")
    ax.add_patch(box)
    ax.text(5, 2.5, label, ha="center", va="center", fontsize=11,
            color="#666666", style="italic")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path



def plan_diagram(question_text: str) -> dict:
    """Decide what diagram (if any) a question needs, and supply its structure.
    Returns {'type': 'food_chain'|'cycle'|'complex'|'none', 'items': [...],
    'caption': '...'}. The LLM only classifies and lists items — it never draws."""
    system = (
        "You analyze a diagram-related exam question and decide how to illustrate it.\n"
        "Return ONLY JSON: {\"type\": \"...\", \"items\": [...], \"caption\": \"...\"}.\n"
        "'type' must be one of:\n"
        "- 'food_chain': a linear food chain / sequence. Provide 'items' as an "
        "ordered list of 3-6 labels, e.g. ['Sun','Grass','Rabbit','Fox'].\n"
        "- 'cycle': a repeating cycle (water cycle, life cycle). Provide 'items' "
        "as an ordered list of 3-6 stage labels.\n"
        "- 'complex': anatomy or detailed structures that cannot be drawn simply "
        "(flower parts, human organs, cell structure). Leave 'items' empty [].\n"
        "- 'none': the question does not actually need a diagram. Leave 'items' [].\n"
        "'caption' is a short instruction line for the diagram (e.g. 'Label the "
        "stages of the water cycle' or 'Draw and label the parts of a flower').\n"
        "Only use 'food_chain' or 'cycle' when you are confident of the correct, "
        "factual items. If unsure, use 'complex'. No text outside the JSON."
    )
    resp = _client.chat.completions.create(
        model=config.TEXT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": question_text},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    data = json.loads(resp.choices[0].message.content)
    return {
        "type": data.get("type", "none"),
        "items": data.get("items", []),
        "caption": data.get("caption", ""),
    }


def render_diagram_for_question(plan: dict, output_path: str) -> str | None:
    """Given a diagram plan, draw the right diagram and return its path.
    Returns None if no diagram is needed."""
    d_type = plan.get("type")
    items = plan.get("items", [])
    caption = plan.get("caption", "Draw and label the diagram")

    if d_type == "food_chain" and len(items) >= 2:
        return draw_food_chain(items, output_path)
    if d_type == "cycle" and len(items) >= 3:
        return draw_cycle(items, output_path)
    if d_type == "complex":
        return draw_blank_space(caption, output_path)
    return None   # 'none' or invalid — no diagram


if __name__ == "__main__":
    tests = [
        "Draw a food chain that could exist in a forest ecosystem.",
        "Label the stages of the water cycle.",
        "Draw and label the parts of a flower.",
        "What is 2 + 2?",
    ]
    for i, q in enumerate(tests):
        plan = plan_diagram(q)
        print(f"\nQ: {q}")
        print(f"   plan: {plan}")
        path = render_diagram_for_question(
            plan, os.path.join(config.OUTPUT_DIR, f"plan_test_{i}.png"))
        print(f"   drawn: {path}")