from abc import ABC, abstractmethod


# Copy of the course's Player base class, renamed with the team suffix as the
# submission instructions require (Player -> PlayerJinhaJang).
class PlayerJinhaJang(ABC):
    def __init__(self, color):
        self.color = color

    @abstractmethod
    def take_turn(self, board, time):
        pass
