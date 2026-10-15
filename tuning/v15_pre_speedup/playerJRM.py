"""Team JRM's namespaced Player interface for CAS 1102 Project 1.

AI disclosure: ChatGPT generated this file from the supplied Player interface.
See README.txt and llm-usage/ for the declaration and conversation record.
"""
from abc import ABC, abstractmethod


class PlayerJRM(ABC):
    def __init__(self, color):
        self.color = color

    @abstractmethod
    def take_turn(self, board, time):
        """Return (row, column); time is the remaining game clock in ms."""
        raise NotImplementedError
