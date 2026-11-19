"""Draw the example chart from the article."""
import insight_chart as ic

ic.insight_chart(
    ["Jan", "Feb", "Mar", "Apr"],
    {"North": [1200, 1150, 1040, 980], "South": [900, 940, 960, 1010], "West": [700, 720, 690, 710]},
    focus="North", metric="orders", period="Jan to Apr",
    source="Order system extract", path="example.png",
)
