from player import Player

SIZE = 19
EMPTY = -1

class HumanPlayer(Player):
    def __init__(self, color):
        super().__init__(color)


    def take_turn(self, board, time):
        if time == -1:
            print("No time limit")
        else:
            print(f"{time / 1000:.3f} seconds remaining")

        while True:
            chaksu = input("Place the stone.")

            if not "," in chaksu:
                print("Invalid input. Try again")
                continue
            
            TestChaksu = chaksu.split(",")
            if len(TestChaksu) != 2:
                print("Invalid input. Try again")
                continue

            TestRow = TestChaksu[0]
            TestCol = TestChaksu[1]
            try:
                if not (TestRow.isdigit() and 0 <= int(TestRow) < SIZE):
                    print("Invalid input. Try again")
                    continue
            except ValueError:
                print("Invalid input. Try again")
                continue
            try:
                if not (TestCol.isdigit() and 0 <= int(TestCol) < SIZE):
                    print("Invalid input. Try again")
                    continue
            except ValueError:
                print("Invalid input. Try again")
                continue

            if board[int(TestRow)][int(TestCol)] != EMPTY:
                print("Invalid input. Try again")
                continue
            
            return int(TestRow),int(TestCol)

