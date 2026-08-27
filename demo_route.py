"""Deterministic offline demo for task-api-router."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Model:
    name: str
    input_cost_per_1k: float
    output_cost_per_1k: float


MODELS = {
    "deepseek-v4-flash": Model("deepseek-v4-flash", 0.001, 0.002),
    "claude-sonnet": Model("claude-sonnet", 0.003, 0.015),
}


TASKS = (
    {
        "text": "Fix a Python null-pointer bug and explain the root cause.",
        "model": "claude-sonnet",
        "input_tokens": 180,
        "output_tokens": 320,
        "action": "allow",
    },
    {
        "text": "Translate 100 product titles from Chinese to English.",
        "model": "deepseek-v4-flash",
        "input_tokens": 900,
        "output_tokens": 1100,
        "action": "allow",
    },
    {
        "text": "Delete the build directory and reset the repository to the last commit.",
        "model": "deepseek-v4-flash",
        "input_tokens": 140,
        "output_tokens": 120,
        "action": "block",
    },
)


def estimate_cost(model: Model, input_tokens: int, output_tokens: int) -> float:
    input_cost = input_tokens / 1000 * model.input_cost_per_1k
    output_cost = output_tokens / 1000 * model.output_cost_per_1k
    return round(input_cost + output_cost, 6)


def main() -> None:
    print("task-api-router deterministic demo")
    print("=" * 80)

    routed_total = 0.0
    strongest_total = 0.0

    for index, task in enumerate(TASKS, start=1):
        model = MODELS[task["model"]]
        cost = estimate_cost(
            model,
            task["input_tokens"],
            task["output_tokens"],
        )
        routed_total += cost
        strongest_total += estimate_cost(
            MODELS["claude-sonnet"], task["input_tokens"], task["output_tokens"]
        )
        guard_result = (
            "BLOCKED: destructive repository action requires confirmation"
            if task["action"] == "block"
            else "ALLOWED: no local high-risk rule matched"
        )

        print(f"\nTask {index}")
        print(f"Task: {task['text']}")
        print(f"Model: {model.name}")
        print(f"Estimated cost: ${cost:.6f}")
        print(f"Action guard: {guard_result}")

    saved = strongest_total - routed_total
    percent = (saved / strongest_total * 100) if strongest_total else 0.0
    print("\nCost signal")
    print(f"Routed total: ${routed_total:.6f}")
    print(f"Always-strongest baseline: ${strongest_total:.6f}")
    print(f"Estimated saving in this demo: ${saved:.6f} ({percent:.1f}%)")


if __name__ == "__main__":
    main()
