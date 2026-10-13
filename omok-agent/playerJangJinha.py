# AI usage: ChatGPT (Codex) adapted the project's abstract Player interface.
from abc import ABC, abstractmethod


class PlayerJangJinha(ABC):
    def __init__(self, color):
        self.color = color

    @abstractmethod
    def take_turn(self, board, time):
        pass
