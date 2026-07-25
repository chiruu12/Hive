"""Toolkit Workshop — build a complete custom toolkit from scratch.

A hands-on guide to creating toolkits with multiple tools, state management,
input validation, and error handling. Builds a recipe management toolkit.

Run: uv run python examples/28_toolkit_workshop.py
"""

import asyncio
import json
from datetime import UTC, datetime

from hive import Agent, Instructions, Task, Toolkit, tool
from hive.models.anthropic import Anthropic


class RecipeToolkit(Toolkit):
    """A complete toolkit for managing recipes.

    Demonstrates:
    - Multiple related tools in one toolkit
    - State management (in-memory store)
    - Input validation in tool methods
    - Error handling patterns
    - Tool descriptions that guide the agent
    """

    def __init__(self):
        self._recipes: dict[str, dict] = {}
        self._favorites: set[str] = set()

    @tool()
    def add_recipe(
        self,
        name: str,
        ingredients: str,
        instructions: str,
        cuisine: str = "",
        prep_time_minutes: int = 0,
    ) -> str:
        """Add a new recipe to the collection.

        Args:
            name: Recipe name (must be unique).
            ingredients: Comma-separated list of ingredients.
            instructions: Step-by-step cooking instructions.
            cuisine: Cuisine type (e.g. Italian, Mexican, Japanese).
            prep_time_minutes: Preparation time in minutes.
        """
        recipe_id = name.lower().replace(" ", "-")
        if recipe_id in self._recipes:
            return f"Error: Recipe '{name}' already exists. Use update_recipe to modify it."

        self._recipes[recipe_id] = {
            "name": name,
            "ingredients": [i.strip() for i in ingredients.split(",")],
            "instructions": instructions,
            "cuisine": cuisine,
            "prep_time_minutes": prep_time_minutes,
            "created": datetime.now(UTC).isoformat(),
            "times_cooked": 0,
        }
        return f"Added recipe: {name} ({len(ingredients.split(','))} ingredients)"

    @tool()
    def search_recipes(self, query: str = "", cuisine: str = "", max_prep_time: int = 0) -> str:
        """Search recipes by name, ingredient, or cuisine.

        Args:
            query: Search term to match against name or ingredients.
            cuisine: Filter by cuisine type.
            max_prep_time: Maximum preparation time in minutes (0 for any).
        """
        results = []
        for rid, recipe in self._recipes.items():
            if query and query.lower() not in recipe["name"].lower():
                if not any(query.lower() in ing.lower() for ing in recipe["ingredients"]):
                    continue
            if cuisine and recipe["cuisine"].lower() != cuisine.lower():
                continue
            if max_prep_time and recipe["prep_time_minutes"] > max_prep_time:
                continue
            results.append({
                "id": rid,
                "name": recipe["name"],
                "cuisine": recipe["cuisine"],
                "prep_time": recipe["prep_time_minutes"],
                "ingredients": len(recipe["ingredients"]),
            })

        if not results:
            return "No recipes found matching your criteria."
        return json.dumps(results, indent=2)

    @tool()
    def get_recipe(self, recipe_name: str) -> str:
        """Get the full details of a recipe by name.

        Args:
            recipe_name: The name of the recipe to retrieve.
        """
        recipe_id = recipe_name.lower().replace(" ", "-")
        recipe = self._recipes.get(recipe_id)
        if not recipe:
            return f"Recipe '{recipe_name}' not found."
        return json.dumps(recipe, indent=2, default=str)

    @tool()
    def mark_cooked(self, recipe_name: str, rating: str = "") -> str:
        """Record that you cooked a recipe, with an optional rating.

        Args:
            recipe_name: The name of the recipe you cooked.
            rating: Optional rating: loved, liked, okay, or disliked.
        """
        recipe_id = recipe_name.lower().replace(" ", "-")
        recipe = self._recipes.get(recipe_id)
        if not recipe:
            return f"Recipe '{recipe_name}' not found."
        recipe["times_cooked"] += 1
        if rating:
            recipe.setdefault("ratings", []).append(rating)
        return f"Marked '{recipe['name']}' as cooked (total: {recipe['times_cooked']} times)"

    @tool()
    def favorite_recipe(self, recipe_name: str) -> str:
        """Add a recipe to your favorites list.

        Args:
            recipe_name: The name of the recipe to favorite.
        """
        recipe_id = recipe_name.lower().replace(" ", "-")
        if recipe_id not in self._recipes:
            return f"Recipe '{recipe_name}' not found."
        self._favorites.add(recipe_id)
        return f"Added '{recipe_name}' to favorites!"

    @tool()
    def get_meal_plan(self, num_recipes: int = 3) -> str:
        """Generate a simple meal plan from your recipe collection.

        Args:
            num_recipes: Number of recipes to include in the plan.
        """
        if not self._recipes:
            return "No recipes in collection. Add some recipes first!"

        # Prefer favorites, then most-cooked
        ordered = sorted(
            self._recipes.items(),
            key=lambda x: (
                x[0] in self._favorites,
                x[1].get("times_cooked", 0),
            ),
            reverse=True,
        )

        plan = []
        for rid, recipe in ordered[:num_recipes]:
            plan.append({
                "name": recipe["name"],
                "cuisine": recipe["cuisine"],
                "prep_time": f"{recipe['prep_time_minutes']} min",
                "ingredients_count": len(recipe["ingredients"]),
            })

        return json.dumps({"meal_plan": plan}, indent=2)


async def main() -> None:
    provider = Anthropic.lite()

    agent = Agent(
        name="chef-assistant",
        model=provider,
        instructions=Instructions(
            persona="a helpful cooking assistant who loves trying new recipes",
            instructions=[
                "Help users manage their recipe collection",
                "Suggest meal plans based on available recipes",
                "Be enthusiastic about cooking",
            ],
        ),
        toolkits=[RecipeToolkit()],
        max_steps=20,
    )

    result = await agent.run(
        Task(
            instruction=(
                "Let's build a recipe collection! Do the following:\n"
                "1. Add a recipe for 'Spaghetti Carbonara' (Italian, 30 min)\n"
                "   Ingredients: spaghetti, eggs, pancetta, parmesan, black pepper\n"
                "2. Add a recipe for 'Chicken Tacos' (Mexican, 25 min)\n"
                "   Ingredients: chicken breast, tortillas, salsa, avocado, lime\n"
                "3. Add a recipe for 'Miso Ramen' (Japanese, 45 min)\n"
                "   Ingredients: ramen noodles, miso paste, pork, soft-boiled egg, green onion\n"
                "4. Search for all Italian recipes\n"
                "5. Mark the carbonara as cooked and rate it 'loved'\n"
                "6. Favorite the carbonara\n"
                "7. Generate a meal plan for 2 recipes\n"
                "8. Give me a summary of what you did"
            )
        )
    )

    print(f"Status: {result.status}")
    print(f"Steps: {result.steps_taken}, Tool calls: {result.tool_calls_made}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    print(f"\nOutput:\n{result.output}")


if __name__ == "__main__":
    asyncio.run(main())
