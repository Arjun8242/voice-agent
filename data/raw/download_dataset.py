from datasets import load_dataset

ds = load_dataset("bitext/Bitext-retail-ecommerce-llm-chatbot-training-dataset")

selected_intent = {
    "customer_service",
    "human_agent",

    "damaged_delivery",
    "delivery_issue",
    "delivery_time",
    "shipping_costs",
    "wrong_item",

    "cancel_order",
    "change_order",

    "payment_issue",

    "availability",
    "product_information",
    "product_issue",

    "refund_policy",
    "refund_status",
    "return_policy",
    "return_product",

    "request_right_to_rectification"
}

filtered = ds["train"].filter(
    lambda row: row["intent"] in selected_intent
)


print("Total:", len(filtered))

# print(filtered[0])
# print(filtered[1])
# print(filtered[2])
# print(filtered[3])
# print(filtered[4])

from collections import Counter
for intent, count in Counter(filtered["intent"]).most_common():
    print(f"{intent}: {count}")

print(list(set(filtered["intent"])))