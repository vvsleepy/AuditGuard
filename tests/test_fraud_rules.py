from utils.fraud_rules import detect_fraud_signals


def test_duplicate_detection():
    policy = {"meal_cap": 80.0, "require_receipt_over": 25.0}
    line_items = [
        {
            "item_id": "item_1",
            "amount": 42.0,
            "category": "travel",
            "receipt_attached": True,
            "merchant": "Metro Cab",
            "date": "2026-02-18",
            "employee_id": "emp_200",
        },
        {
            "item_id": "item_2",
            "amount": 42.0,
            "category": "travel",
            "receipt_attached": True,
            "merchant": "Metro Cab",
            "date": "2026-02-18",
            "employee_id": "emp_200",
        },
    ]

    signals = detect_fraud_signals(line_items, policy)
    assert signals["item_1"]["reason"] == "DUPLICATE_EXPENSE"
    assert signals["item_2"]["reason"] == "DUPLICATE_EXPENSE"


def test_split_transaction():
    policy = {"meal_cap": 80.0, "require_receipt_over": 25.0}
    line_items = [
        {
            "item_id": "item_3",
            "amount": 40.0,
            "category": "meal",
            "receipt_attached": True,
            "merchant": "Blue Olive Catering",
            "date": "2026-01-16",
            "employee_id": "emp_302",
        },
        {
            "item_id": "item_4",
            "amount": 40.0,
            "category": "meal",
            "receipt_attached": True,
            "merchant": "Blue Olive Catering",
            "date": "2026-01-16",
            "employee_id": "emp_302",
        },
        {
            "item_id": "item_5",
            "amount": 40.0,
            "category": "meal",
            "receipt_attached": True,
            "merchant": "Blue Olive Catering",
            "date": "2026-01-16",
            "employee_id": "emp_302",
        },
    ]

    signals = detect_fraud_signals(line_items, policy)
    assert signals["item_3"]["reason"] == "SPLIT_TRANSACTION"
    assert signals["item_4"]["reason"] == "SPLIT_TRANSACTION"
    assert signals["item_5"]["reason"] == "SPLIT_TRANSACTION"


def test_laundering_detection():
    policy = {"meal_cap": 80.0, "require_receipt_over": 25.0}
    line_items = [
        {
            "item_id": "item_6",
            "amount": 126.4,
            "category": "office",
            "receipt_attached": True,
            "merchant": "NorthStar Tech Supplies",
            "date": "2026-01-18",
            "employee_id": "emp_304",
        },
        {
            "item_id": "item_7",
            "amount": 126.4,
            "category": "office",
            "receipt_attached": True,
            "merchant": "NST Office Supply",
            "date": "2026-01-18",
            "employee_id": "emp_304",
        },
    ]

    signals = detect_fraud_signals(line_items, policy)
    assert signals["item_6"]["reason"] == "MERCHANT_LAUNDERING"
    assert signals["item_7"]["reason"] == "MERCHANT_LAUNDERING"
