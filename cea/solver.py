import json
import sys

import cea
import numpy as np


def as_json(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): as_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [as_json(item) for item in value]
    return value


def solve(payload):
    reactants = payload["reactants"]
    names = [item["species"] for item in reactants]
    moles = np.asarray([item["moles"] for item in reactants], dtype=np.float64)
    reactant_mix = cea.Mixture(names)
    weights = reactant_mix.moles_to_weights(moles)
    product_mix = cea.Mixture(names, products_from_reactants=True)
    pressure = float(payload["pressure"])

    if payload["mode"] == "rocket":
        solver = cea.RocketSolver(product_mix, reactants=reactant_mix)
        solution = cea.RocketSolution(solver)
        solver.solve(
            solution,
            weights,
            pc=pressure,
            pi_p=[float(payload["exitPressureRatio"])],
            tc=float(payload["temperature"]),
        )
        return {
            "mode": "rocket",
            "converged": bool(solution.converged),
            "chamberPressure": pressure,
            "chamberTemperature": float(payload["temperature"]),
            "exitPressureRatio": float(payload["exitPressureRatio"]),
            "stations": {
                "pressure": as_json(solution.P),
                "temperature": as_json(solution.T),
                "isp": as_json(solution.Isp),
                "ispVacuum": as_json(solution.Isp_vacuum),
                "mach": as_json(solution.Mach),
                "areaRatio": as_json(solution.ae_at),
                "cStar": as_json(solution.c_star),
                "thrustCoefficient": as_json(solution.coefficient_of_thrust),
            },
        }

    solver = cea.EqSolver(product_mix, reactants=reactant_mix, transport=True)
    solution = cea.EqSolution(solver)
    equilibrium_type = payload.get("equilibriumType", "HP")
    if equilibrium_type == "HP":
        reactant_enthalpy = reactant_mix.calc_property(
            cea.ENTHALPY, weights, float(payload["temperature"])
        )
        solver.solve(solution, cea.HP, reactant_enthalpy / cea.R, pressure, weights)
    else:
        solver.solve(
            solution,
            cea.TP,
            float(payload["temperature"]),
            pressure,
            weights,
        )

    properties = (
        "T",
        "P",
        "density",
        "enthalpy",
        "entropy",
        "MW",
        "gamma_s",
        "cp",
        "cv",
        "viscosity",
        "conductivity_eq",
        "Pr_eq",
    )
    return {
        "mode": "equilibrium",
        "equilibriumType": equilibrium_type,
        "converged": bool(solution.converged),
        "properties": {name: as_json(getattr(solution, name)) for name in properties},
        "massFractions": as_json(solution.mass_fractions),
        "moleFractions": as_json(solution.mole_fractions),
    }


if __name__ == "__main__":
    try:
        print(json.dumps(solve(json.load(sys.stdin)), allow_nan=False))
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error
