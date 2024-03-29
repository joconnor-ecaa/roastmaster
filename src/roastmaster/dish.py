"""dish.py."""

import pandas as pd
import pulp  # type: ignore

import roastmaster.models as models


class DishOpt:
    """Represents a dish that can be cooked in an oven.

    Args:
        model (pulp.LpProblem): The optimization model.
        system_config (models.System): The system configuration.
        dish_config (models.Dish): The dish configuration.

    Attributes:
        name (str): The name of the dish.
        size (float): The size of the dish.
        serve_hot (float): The weight of the dish when served hot.
        oven_mins (int): The desired cooking time in minutes.
        system_config (models.System): The system configuration.

    Methods:
        get_score(): Calculates the score of the dish based on temperature and oven openings.
        get_results(): Retrieves the results of the optimization model.

    """

    def __init__(
        self,
        model: pulp.LpProblem,
        system_config: models.System,
        dish_config: models.Dish,
    ) -> None:
        """Initializes a new instance of the Dish class.

        Args:
            model (pulp.LpProblem): The optimization model.
            system_config (models.System): The system configuration.
            dish_config (models.Dish): The dish configuration.
        """
        self.name = dish_config.name
        self.dish_config = dish_config

        self.system_config = system_config
        self.time_range = system_config.get_time_range()

        # initialise some dynamic decisions / variables at time = T-1
        self.put_in: pulp.LpVariable = {-self.system_config.time_increment: 0}
        self.take_out: pulp.LpVariable = {-self.system_config.time_increment: 0}
        self.is_in: pulp.LpVariable = {-self.system_config.time_increment: 0}
        self.space_used: pulp.LpVariable = {-self.system_config.time_increment: 0}
        self.time_cooked: pulp.LpVariable = {-self.system_config.time_increment: 0}

        for time in self.time_range:
            # decision variables -- put into oven at this timestep
            self.put_in[time] = pulp.LpVariable(
                f"{self.dish_config.name}_in_{time}", cat="Binary"
            )
            # take out of oven at this timestep
            self.take_out[time] = pulp.LpVariable(
                f"{self.dish_config.name}_out_{time}", cat="Binary"
            )
            # in-ness = last inness + put in - take out
            self.is_in[time] = (
                self.is_in[time - self.system_config.time_increment]
                + self.put_in[time]
                - self.take_out[time]
            )
            # space used = in-ness * size
            self.space_used[time] = self.is_in[time] * self.dish_config.size
            # time cooked = last time cooked + inness * time increment
            self.time_cooked[time] = (
                self.time_cooked[time - self.system_config.time_increment]
                + self.is_in[time] * self.system_config.time_increment
            )
            # penalty for multiple put-ins -- first e.g. 5 mins after
            # putting in do not count towards cooking time
            self.time_cooked[time] -= (
                self.put_in[time] * self.system_config.oven.warm_up_time
            )

            # binary constraints on inness
            model += self.is_in[time] >= 0
            model += self.is_in[time] <= 1
            model += (
                self.put_in[time] + self.is_in[time - self.system_config.time_increment]
                <= 1
            )
            model += (
                self.is_in[time - self.system_config.time_increment]
                - self.take_out[time]
                >= 0
            )

        # cooking time constraint -- total cooking time == desired cooking time
        # TODO: add some tolerance here, maybe user-defined
        model += (
            self.time_cooked[self.system_config.total_time]
            == self.dish_config.cooking_time_mins
        )
        model += self.is_in[self.system_config.total_time] == 0

    def get_score(self) -> pulp.LpAffineExpression:
        """Calculates the score of the dish based on temperature and oven openings.

        Returns:
            pulp.LpAffineExpression: The score of the dish.

        """
        # reward hot food
        dish_temp = (
            3
            * self.is_in[
                self.system_config.total_time - self.system_config.time_increment
            ]
            + 2
            * self.is_in[
                self.system_config.total_time - 2 * self.system_config.time_increment
            ]
            + self.is_in[
                self.system_config.total_time - 3 * self.system_config.time_increment
            ]
        )

        # penalise oven openings
        oven_openings = sum(self.put_in[time] for time in self.put_in) + sum(
            self.take_out[time] for time in self.take_out
        )
        return (
            dish_temp * self.dish_config.serve_hot_weight
        ) - oven_openings * self.system_config.oven.oven_opening_penalty

    def get_results(self) -> pd.DataFrame:
        """Retrieves the results of the optimization model.

        Returns:
            pd.DataFrame: The results of the optimization model.

        """
        is_in: pd.Series = pd.Series(
            {time: self.is_in[time].value() for time in self.time_range}
        )
        put_in: pd.Series = pd.Series(
            {time: self.put_in[time].value() for time in self.time_range}
        )
        take_out: pd.Series = pd.Series(
            {time: self.take_out[time].value() for time in self.time_range}
        )
        time_cooked: pd.Series = pd.Series(
            {time: self.time_cooked[time].value() for time in self.time_range}
        )
        space_used: pd.Series = pd.Series(
            {time: self.space_used[time].value() for time in self.time_range}
        )
        return pd.DataFrame(
            {
                "is_in": is_in,
                "put_in": put_in,
                "take_out": take_out,
                "time_cooked": time_cooked,
                "space_used": space_used,
            }
        )
