def score(q, k):
    return (q @ k.T) / 8  # 100% vectorised
