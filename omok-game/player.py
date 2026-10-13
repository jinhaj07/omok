from abc import ABC, abstractmethod


class Player(ABC):
    def __init__(self, color):
        self.color = color

    @abstractmethod
    def take_turn(self, board, time):
        pass