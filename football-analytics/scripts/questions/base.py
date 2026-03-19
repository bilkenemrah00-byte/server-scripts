from utils.validators import find_bet_values, get_odds_value, implied_probability

def make_answer(question, conclusion, confidence, positive_signals, total_signals, details, data_sources, calculation=None, skipped=False, skip_reason=None, our_prediction=None, market_edge=None):
    answer = {"question": question, "conclusion": conclusion, "confidence": confidence, "signals": {"positive": positive_signals, "total": total_signals, "details": details}, "data_sources": data_sources}
    if calculation: answer["calculation"] = calculation
    if skipped: answer["skipped"] = True; answer["reason"] = skip_reason or "insufficient_data"
    if our_prediction is not None: answer.setdefault("calculation", {})["our_prediction"] = our_prediction
    if market_edge is not None: answer.setdefault("calculation", {})["market_edge"] = market_edge
    return answer

def no_odds_skip(question):
    return make_answer(question=question, conclusion="Veri yetersiz — odds data mevcut değil", confidence="N/A", positive_signals=0, total_signals=0, details=["Odds data unavailable"], data_sources=[], skipped=True, skip_reason="no_odds_data")

def confidence_from_signals(positive, total):
    ratio = positive / total if total > 0 else 0
    return "HIGH" if ratio >= 0.67 else "MEDIUM" if ratio >= 0.34 else "LOW"

def get_over_under_odds(odds_response, label):
    values = find_bet_values(odds_response, bet_id=5)
    return get_odds_value(values, label)

def get_btts_odds(odds_response, label="Yes"):
    values = find_bet_values(odds_response, bet_id=8)
    return get_odds_value(values, label)

def get_first_half_ou_odds(odds_response, label):
    values = find_bet_values(odds_response, bet_id=6)
    return get_odds_value(values, label)

def get_second_half_ou_odds(odds_response, label):
    values = find_bet_values(odds_response, bet_id=26)
    return get_odds_value(values, label)
