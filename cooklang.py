import itertools
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Mapping, Optional, Sequence, Tuple, Union, List


@dataclass
class Quantity:
    amount: Union[int, float, Fraction]
    unit: Optional[str] = None

    @classmethod
    def add_optional(
        cls, a: Optional["Quantity"], b: Optional["Quantity"]
    ) -> Optional["Quantity"]:
        if a and b:
            return a + b
        elif a or b:
            return a or b
        return None

    def __add__(self, other: "Quantity") -> "Quantity":
        if self.unit != other.unit:
            raise ValueError(f"Cannot add unit {self.unit} to {other.unit}")
        if type(self.amount) != type(other.amount):  # noqa: E721
            raise ValueError(
                "Cannot add quantities with types "
                + f"{type(self.amount)} and {type(other.amount)}"
            )
        # pyre-ignore[6]: pyre doesn't refine types on the comparison above
        new_amount = self.amount + other.amount
        if isinstance(new_amount, float):
            new_amount = round(new_amount, 1)
        return Quantity(
            amount=new_amount,
            unit=self.unit,
        )


@dataclass
class Timer:
    name: str
    quantity: Optional[Quantity] = None

    @classmethod
    def parse(cls, raw: str) -> "Timer":
        name, raw_amount = re.findall(r"^~([^{]*)(?:{([^}]*)})?", raw)[0]
        matches = re.findall(r"([^%}]+)%?([\w]+)?", raw_amount)
        return Timer(name, _get_quantity(matches))

    def __add__(self, other: "Timer") -> "Timer":
        if self.name != other.name:
            raise ValueError(
                f"Cannot add timer {self.name} with {other.name}",
            )
        return Timer(
            name=self.name,
            quantity=Quantity.add_optional(self.quantity, other.quantity),
        )


@dataclass
class Ingredient:
    name: str
    location: Tuple[int, int, int]
    quantity: Optional[Quantity] = None

    @classmethod
    def parse(
        cls,
        match: re.Match,
        step_index: int,
        steps: List[str],
        current_ingredients: List,
    ) -> "Ingredient":
        raw = match.group()
        name, raw_amount = re.findall(r"^@([^{]+)(?:{([^}]*)})?", raw)[0]
        matches = re.findall(r"([^%}]+)%?([\w]+)?", raw_amount)

        # get the location of the ingredient in the step str. we do this by searching the current step, but only after the end of the last ingredient's location.
        ingredients_on_current_step = [
            i for i in current_ingredients if i.location[0] == step_index
        ]
        last_ingr_index = (
            ingredients_on_current_step[-1].location[2]
            if len(ingredients_on_current_step) > 0
            else 0
        )
        location_match = re.search(name, steps[step_index][last_ingr_index:])
        location = (
            step_index,
            location_match.start() + last_ingr_index,
            location_match.end() + last_ingr_index,
        )

        return Ingredient(name, location, _get_quantity(matches))

    def __add__(self, other: "Ingredient") -> "Ingredient":
        if self.name != other.name:
            raise ValueError(
                f"Cannot add ingredient {self.name} with {other.name}",
            )
        return Ingredient(
            name=self.name,
            location=self.location,
            quantity=Quantity.add_optional(self.quantity, other.quantity),
        )


@dataclass
class Recipe:
    metadata: Mapping[str, str]
    ingredients: Sequence[Ingredient]
    steps: Sequence[str]
    cookware: Sequence[str]
    timers: Sequence[Timer]

    @classmethod
    def parse(cls, raw: str) -> "Recipe":
        raw_without_comments = re.sub(r"(--[^\n]+|\[-.*-\])", "", raw)
        raw_paragraphs = list(
            filter(None, map(str.strip, raw_without_comments.split("\n")))
        )

        raw_steps = list(
            filter(
                lambda x: not x.startswith(">>"),
                raw_paragraphs,
            )
        )
        steps = [
            re.sub(
                r"(?:@|#)(\w[\w ]*)({[^}]*})?",
                r"\1",
                re.sub(
                    r"~[\w ]*\{([^}%]*)(?:%([^}]+))?}",
                    r"\1 \2",
                    raw_step,
                ),
            )
            for raw_step in raw_steps
        ]

        ingr_pat = re.compile("@(?:(?:[\w ]+?){[^}]*}|[\w]+)")
        ingredients = []
        for raw_step_index, raw_step in enumerate(raw_steps):
            for ingr_match in ingr_pat.finditer(raw_step):
                ingredients.append(
                    Ingredient.parse(ingr_match, raw_step_index, steps, ingredients)
                )

        cookware = list(
            itertools.chain(
                *map(
                    lambda raw_step: list(
                        map(
                            lambda s: s[1] or s[0],
                            re.findall(
                                r"#(([\w ]+?){[^}]*}|[\w]+)",
                                raw_step,
                            ),
                        )
                    ),
                    raw_steps,
                )
            )
        )
        timers = list(
            itertools.chain(
                *map(
                    lambda raw_step: list(
                        map(
                            lambda s: Timer.parse(s),
                            re.findall(
                                r"~(?:(?:[\w ]*?){[^}]*}|[\w]+)",
                                raw_step,
                            ),
                        )
                    ),
                    raw_steps,
                )
            )
        )

        def _remove_duplicates(
            ingredients: Sequence[Ingredient],
        ) -> Sequence[Ingredient]:
            name_to_ingredient = {}
            added_ingredients = set()
            for i in ingredients:
                if i.name not in name_to_ingredient.keys():
                    name_to_ingredient[i.name] = i
                else:
                    name_to_ingredient[i.name] += i
                added_ingredients.add(i.name)
            return list(name_to_ingredient.values())

        ingredients = _remove_duplicates(ingredients)

        def _extract_metadata(raw_line: str) -> Optional[Tuple[str, str]]:
            res = re.search(r"^>> ?([^:]+): ?(.*)$", raw_line)
            if not res:
                return None
            return (res.group(1).strip(), res.group(2).strip())

        raw_metadata = list(
            filter(
                lambda x: x.startswith(">>"),
                raw_paragraphs,
            )
        )
        metadata = dict(
            filter(
                None,
                (_extract_metadata(raw_line) for raw_line in raw_metadata),
            )
        )

        return Recipe(
            metadata=metadata,
            ingredients=ingredients,
            cookware=cookware,
            timers=timers,
            steps=steps,
        )


def _get_quantity(matches: Sequence[Sequence[str]]) -> Optional[Quantity]:
    if not matches:
        return None

    match = matches[0]
    amount_as_str = match[0]
    if not amount_as_str:
        return None
    if "." in amount_as_str:
        amount = float(amount_as_str)
    elif "/" in amount_as_str:
        amount = Fraction(amount_as_str)
    else:
        amount = int(amount_as_str)
    unit = str(match[1]) if match[1] else None
    return Quantity(amount, unit)
