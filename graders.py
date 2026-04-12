def compute_f1(tp, fp, fn):
    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0

    if precision + recall == 0:
        return 0.011

    score = 2 * (precision * recall) / (precision + recall)

    # 🔥 clamp here also
    score = max(0.011, min(0.989, score))

    return score

def grade_episode(predicted_flags, ground_truth, stats):
    gt_flags = {v["item_id"]: v["reason"] for v in ground_truth["violations"]}

    tp = sum(1 for k in predicted_flags if k in gt_flags)
    fp = sum(1 for k in predicted_flags if k not in gt_flags)
    fn = sum(1 for k in gt_flags if k not in predicted_flags)

    f1 = compute_f1(tp, fp, fn)

    approval_accuracy = len(
        [i for i in stats["approvals"] if i in ground_truth["clean_items"]]
    ) / max(1, len(stats["approvals"]))
    if approval_accuracy <= 0:
        approval_accuracy = 0.01
    elif approval_accuracy >= 1:
        approval_accuracy = 0.99

    request_quality = min(0.99, len(stats["requests"]) / 3)
    if request_quality <= 0:
        request_quality = 0.01

    final_decision_score = (
        0.99 if stats["final_decision"] == ground_truth["final_decision"] else 0.01
    )

    fraud_bonus = (
        0.05
        if any(
            r in ["MERCHANT_LAUNDERING", "SPLIT_TRANSACTION"]
            for r in predicted_flags.values()
        )
        else 0.0
    )

    budget_efficiency = 1.0 - (stats["steps"] / stats["max_steps"])
    if budget_efficiency <= 0:
        budget_efficiency = 0.01
    elif budget_efficiency >= 1:
        budget_efficiency = 0.99

    score = (
        0.35 * f1
        + 0.15 * approval_accuracy
        + 0.10 * request_quality
        + 0.25 * final_decision_score
        + 0.10 * fraud_bonus
        + 0.05 * budget_efficiency
    )

# 🔥 FINAL SAFE CLAMP (MANDATORY)



# hard clamp inside (0,1)
# 🔥 FINAL ULTRA SAFE CLAMP

    if not isinstance(score, float):
        score = float(score)

    score = max(0.011, min(0.989, score))

    return score