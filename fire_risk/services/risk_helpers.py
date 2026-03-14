def classify_dimension_score(score):
    if score >= 75:
        return "Very High"
    elif score >= 60:
        return "High"
    elif score >= 40:
        return "Moderate"
    else:
        return "Low"


def build_block_advisory_narrative(environment_score, fuel_score, behaviour_score, response_score):
    env_level = classify_dimension_score(environment_score)
    fuel_level = classify_dimension_score(fuel_score)
    beh_level = classify_dimension_score(behaviour_score)
    res_level = classify_dimension_score(response_score)

    advice = []
    if environment_score >= 60:
        advice.append(
            f"Environment risk is {env_level.lower()} ({environment_score}). Priority actions should include improving spacing around shelters where feasible, keeping access paths clear for emergency movement, reducing congestion around shared facilities, and strengthening basic site-level firebreak arrangements."
        )
    elif environment_score >= 40:
        advice.append(
            f"Environment risk is {env_level.lower()} ({environment_score}). Site planning controls should be maintained, with attention to blocked access routes, encroachment between shelters, and localized congestion that could accelerate fire spread."
        )
    else:
        advice.append(
            f"Environment risk is {env_level.lower()} ({environment_score}). Current site conditions appear relatively better controlled, but routine monitoring of spacing, accessibility, and exposure points should continue."
        )

    if fuel_score >= 60:
        advice.append(
            f"Fuel risk is {fuel_level.lower()} ({fuel_score}). This suggests a high presence or poor management of combustible materials. Actions should focus on reducing dry waste accumulation, improving safe storage of fuel and flammables, keeping cooking areas clear, and removing unnecessary burnable materials from around shelters."
        )
    elif fuel_score >= 40:
        advice.append(
            f"Fuel risk is {fuel_level.lower()} ({fuel_score}). Targeted action is needed to improve housekeeping, waste removal, and safer storage of combustible items."
        )
    else:
        advice.append(
            f"Fuel risk is {fuel_level.lower()} ({fuel_score}). Fuel load appears comparatively lower, but regular waste management and safe storage practices should be sustained."
        )

    if behaviour_score >= 60:
        advice.append(
            f"Behaviour risk is {beh_level.lower()} ({behaviour_score}). Community fire prevention messaging should be intensified. Key priorities include safer cooking behaviour, reducing open flames inside or near shelters, improving child supervision around ignition sources, and reinforcing reporting of unsafe practices."
        )
    elif behaviour_score >= 40:
        advice.append(
            f"Behaviour risk is {beh_level.lower()} ({behaviour_score}). Continued awareness activities are needed, especially around cooking safety, flame use, and day-to-day fire prevention habits."
        )
    else:
        advice.append(
            f"Behaviour risk is {beh_level.lower()} ({behaviour_score}). Behavioural risk appears relatively lower, though routine awareness and reinforcement should continue."
        )

    if response_score >= 60:
        advice.append(
            f"Response risk is {res_level.lower()} ({response_score}). Response capacity needs urgent strengthening. Recommended measures include improving access to extinguishing materials, refresher training for community volunteers, clear escalation and reporting arrangements, and ensuring rapid access for first responders."
        )
    elif response_score >= 40:
        advice.append(
            f"Response risk is {res_level.lower()} ({response_score}). Preparedness systems should be reinforced through targeted checks on equipment, volunteer readiness, and communication pathways."
        )
    else:
        advice.append(
            f"Response risk is {res_level.lower()} ({response_score}). Response arrangements appear relatively stronger, but equipment checks, drills, and readiness reviews should continue."
        )

    highest_dim = max({
        "Environment": environment_score,
        "Fuel": fuel_score,
        "Behaviour": behaviour_score,
        "Response": response_score,
    }, key=lambda k: {
        "Environment": environment_score,
        "Fuel": fuel_score,
        "Behaviour": behaviour_score,
        "Response": response_score,
    }[k])

    overall = (
        f"The highest contributing susceptibility dimension for this block is {highest_dim}. Risk reduction efforts should prioritize this area first, while maintaining integrated action across all four dimensions."
    )

    return advice, overall
