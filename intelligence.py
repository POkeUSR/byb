import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class StructureState:
    trend: str
    breakout_status: str
    support_holding: bool
    resistance_level: Optional[float]
    support_level: Optional[float]
    volatility_pct: float
    last_move_pct: float


class MarketContextEngine:
    def evaluate(self, btc_context: Optional[dict]) -> Dict[str, Any]:
        prices = (btc_context or {}).get("prices", [])
        if len(prices) < 30:
            return {
                "state": "UNKNOWN",
                "score": 0,
                "summary": "Insufficient BTC context",
                "btc_change_pct": None,
                "volatility_pct": None,
            }

        window = prices[-30:]
        start = window[0]
        end = window[-1]
        btc_change = ((end - start) / start) * 100 if start else 0
        mean = sum(window) / len(window)
        variance = sum((price - mean) ** 2 for price in window) / len(window)
        volatility = ((variance ** 0.5) / mean) * 100 if mean else 0

        if btc_change > 0.25 and volatility < 1.2:
            state = "STABLE_BULLISH"
            score = 2
            summary = "BTC stable with positive drift"
        elif btc_change < -0.35:
            state = "WEAK"
            score = -2
            summary = "BTC pressure reduces continuation quality"
        elif volatility > 1.8:
            state = "VOLATILE"
            score = -1
            summary = "Broader market volatility is elevated"
        else:
            state = "STABLE"
            score = 1
            summary = "Broader market conditions are acceptable"

        return {
            "state": state,
            "score": score,
            "summary": summary,
            "btc_change_pct": round(btc_change, 4),
            "volatility_pct": round(volatility, 4),
        }


class StructureAnalyzer:
    def analyze(self, prices: List[float]) -> StructureState:
        if len(prices) < 20:
            return StructureState("UNKNOWN", "UNKNOWN", False, None, None, 0, 0)

        recent = prices[-20:]
        previous = prices[-40:-20] if len(prices) >= 40 else prices[:-20]
        last = recent[-1]
        first = recent[0]
        last_move = ((last - first) / first) * 100 if first else 0

        mean = sum(recent) / len(recent)
        variance = sum((price - mean) ** 2 for price in recent) / len(recent)
        volatility = ((variance ** 0.5) / mean) * 100 if mean else 0

        support = min(recent[:-1]) if len(recent) > 1 else last
        resistance = max(previous) if previous else max(recent[:-1])
        support_holding = last >= support * 1.001

        if resistance and last > resistance * 1.002:
            breakout = "BREAKOUT_CONFIRMED"
        elif resistance and last > resistance * 0.998:
            breakout = "TESTING_RESISTANCE"
        else:
            breakout = "NO_BREAKOUT"

        if last_move > 0.5:
            trend = "UP"
        elif last_move < -0.5:
            trend = "DOWN"
        else:
            trend = "RANGE"

        return StructureState(
            trend=trend,
            breakout_status=breakout,
            support_holding=support_holding,
            resistance_level=round(resistance, 8) if resistance else None,
            support_level=round(support, 8) if support else None,
            volatility_pct=round(volatility, 4),
            last_move_pct=round(last_move, 4),
        )


class TrapDetector:
    def evaluate(self, prices: List[float], volumes: List[float], structure: StructureState) -> Dict[str, Any]:
        if len(prices) < 10 or len(volumes) < 10:
            return {"probability": 0.35, "flags": ["Insufficient trap history"]}

        recent_prices = prices[-10:]
        recent_volumes = volumes[-10:]
        flags = []
        trap_score = 0.0

        last_move = structure.last_move_pct
        last_price = recent_prices[-1]
        high = max(recent_prices)
        low = min(recent_prices)
        range_pct = ((high - low) / low) * 100 if low else 0

        avg_volume = sum(recent_volumes[:-1]) / max(len(recent_volumes[:-1]), 1)
        last_volume = recent_volumes[-1]
        volume_ratio = last_volume / avg_volume if avg_volume else 0

        if last_move > 3 and structure.breakout_status != "BREAKOUT_CONFIRMED":
            trap_score += 0.3
            flags.append("Vertical move without confirmed breakout")
        if high and last_price < high * 0.985:
            trap_score += 0.25
            flags.append("Immediate rejection from local high")
        if volume_ratio > 3 and abs(last_move) < 0.35:
            trap_score += 0.25
            flags.append("Volume spike without price continuation")
        if range_pct > 4:
            trap_score += 0.2
            flags.append("Chaotic short-term range")
        if structure.trend == "DOWN":
            trap_score += 0.15
            flags.append("Short-term trend is down")

        probability = min(0.95, trap_score)
        if not flags:
            flags.append("No major trap flags")

        return {
            "probability": round(probability, 2),
            "flags": flags,
        }


class RelativeStrengthEngine:
    def evaluate(self, prices: List[float], btc_prices: List[float]) -> Dict[str, Any]:
        if len(prices) < 30 or len(btc_prices) < 30:
            return {"state": "UNKNOWN", "value": None, "summary": "Insufficient relative strength data"}

        asset_window = prices[-30:]
        btc_window = btc_prices[-30:]
        asset_change = ((asset_window[-1] - asset_window[0]) / asset_window[0]) if asset_window[0] else 0
        btc_change = ((btc_window[-1] - btc_window[0]) / btc_window[0]) if btc_window[0] else 0
        rs = asset_change - btc_change

        if rs > 0.015:
            state = "LEADER"
            summary = "Asset is outperforming BTC"
        elif rs > 0:
            state = "POSITIVE"
            summary = "Asset is modestly stronger than BTC"
        elif rs < -0.015:
            state = "LAGGARD"
            summary = "Asset is underperforming BTC"
        else:
            state = "NEUTRAL"
            summary = "Asset is moving close to BTC"

        return {
            "state": state,
            "value": round(rs, 5),
            "summary": summary,
        }


class RiskEvaluator:
    def evaluate(self, structure: StructureState, trap: Dict[str, Any], market_context: Dict[str, Any]) -> Dict[str, Any]:
        risk_points = 0
        reasons = []

        if trap["probability"] >= 0.6:
            risk_points += 3
            reasons.append("High trap probability")
        elif trap["probability"] >= 0.35:
            risk_points += 2
            reasons.append("Moderate trap probability")

        if structure.volatility_pct > 2.5:
            risk_points += 2
            reasons.append("Elevated short-term volatility")
        elif structure.volatility_pct > 1.2:
            risk_points += 1
            reasons.append("Moderate volatility")

        if market_context.get("score", 0) < 0:
            risk_points += 1
            reasons.append("Market context is not supportive")

        if not structure.support_holding:
            risk_points += 1
            reasons.append("Support is not clearly holding")

        if risk_points >= 4:
            level = "HIGH"
        elif risk_points >= 2:
            level = "MEDIUM"
        else:
            level = "LOW"
            reasons.append("No major risk flags")

        return {"level": level, "reasons": reasons}


class SetupClassifier:
    def classify(
        self,
        alert: Dict[str, Any],
        structure: StructureState,
        market_context: Dict[str, Any],
        trap: Dict[str, Any],
        relative_strength: Dict[str, Any],
        risk: Dict[str, Any],
    ) -> Dict[str, Any]:
        points = 0
        score = alert.get("score", 0)

        if score >= 80:
            points += 3
        elif score >= 50:
            points += 2
        elif score >= 20:
            points += 1

        if structure.breakout_status == "BREAKOUT_CONFIRMED":
            points += 2
        elif structure.breakout_status == "TESTING_RESISTANCE":
            points += 1

        if structure.trend == "UP":
            points += 1
        if structure.support_holding:
            points += 1
        if relative_strength.get("state") == "LEADER":
            points += 2
        elif relative_strength.get("state") == "POSITIVE":
            points += 1
        points += market_context.get("score", 0)

        if trap["probability"] >= 0.6:
            points -= 3
        elif trap["probability"] >= 0.35:
            points -= 1
        if risk["level"] == "HIGH":
            points -= 2
        elif risk["level"] == "MEDIUM":
            points -= 1

        if points >= 7:
            tier = "A-TIER"
        elif points >= 4:
            tier = "B-TIER"
        else:
            tier = "C-TIER"

        if trap["probability"] >= 0.6:
            status = "TRAP"
        elif structure.breakout_status == "BREAKOUT_CONFIRMED" and structure.trend == "UP":
            status = "CONFIRMED"
        elif structure.trend == "DOWN":
            status = "FAILED"
        else:
            status = "RAW"

        return {
            "tier": tier,
            "status": status,
            "classification_score": points,
        }


class SignalIntelligenceEngine:
    def __init__(self):
        self.market_context = MarketContextEngine()
        self.structure = StructureAnalyzer()
        self.trap = TrapDetector()
        self.relative_strength = RelativeStrengthEngine()
        self.risk = RiskEvaluator()
        self.classifier = SetupClassifier()

    def enrich(self, alert: Dict[str, Any], context: dict, btc_context: Optional[dict]) -> Dict[str, Any]:
        prices = context.get("prices", [])
        volumes = context.get("volumes", [])
        btc_prices = (btc_context or {}).get("prices", prices)

        market_context = self.market_context.evaluate(btc_context)
        structure = self.structure.analyze(prices)
        relative_strength = self.relative_strength.evaluate(prices, btc_prices)
        trap = self.trap.evaluate(prices, volumes, structure)
        risk = self.risk.evaluate(structure, trap, market_context)
        classification = self.classifier.classify(alert, structure, market_context, trap, relative_strength, risk)

        enriched = dict(alert)
        enriched["intelligence"] = {
            "tier": classification["tier"],
            "signal_status": classification["status"],
            "classification_score": classification["classification_score"],
            "risk_level": risk["level"],
            "risk_reasons": risk["reasons"],
            "trap_probability": trap["probability"],
            "trap_flags": trap["flags"],
            "market_context": market_context,
            "relative_strength": relative_strength,
            "structure": {
                "trend": structure.trend,
                "breakout_status": structure.breakout_status,
                "support_holding": structure.support_holding,
                "support_level": structure.support_level,
                "resistance_level": structure.resistance_level,
                "volatility_pct": structure.volatility_pct,
                "last_move_pct": structure.last_move_pct,
            },
            "explanation": self._build_explanation(classification, risk, trap, market_context, relative_strength, structure),
            "evaluated_at": time.time() * 1000,
        }
        return enriched

    def _build_explanation(
        self,
        classification: Dict[str, Any],
        risk: Dict[str, Any],
        trap: Dict[str, Any],
        market_context: Dict[str, Any],
        relative_strength: Dict[str, Any],
        structure: StructureState,
    ) -> str:
        parts = [
            f"{classification['tier']} setup",
            f"status {classification['status']}",
            f"risk {risk['level']}",
            f"market {market_context.get('state')}",
            f"RS {relative_strength.get('state')}",
            f"structure {structure.breakout_status}",
            f"trap {trap['probability']}",
        ]
        return "; ".join(parts)
