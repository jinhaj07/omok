"""Optional local-play support, derived from the uploaded Task 1 file.
AI disclosure: ChatGPT renamed imports/classes with the JRM suffix. Original behavior otherwise retained.
The competition agent depends only on smartplayerJRM.py and playerJRM.py.
"""
SIZE = 19
EMPTY = -1
AXES = ((0, 1), (1, 0), (1, 1), (1, -1))


class BoardJRM:
    def __init__(self):
        self._grid = [[EMPTY for _ in range(SIZE)] for _ in range(SIZE)]


    def GetBoard(self):
        return [row[:] for row in self._grid]


    def ValidPosition(self, row, col):
        return (0 <= row < SIZE and
                0 <= col < SIZE and
                self._grid[row][col] == EMPTY)
    

    def PlaceStone(self, row, col, color):
        if not self.ValidPosition(row, col):
            raise ValueError
        self._grid[row][col] = color


    def TakeStone(self, row, col, color):
        for i in [-3, 0, 3]:
            for j in [-3, 0, 3]:
                if 0 <= row + i < SIZE and 0 <= col + j < SIZE and self._grid[row + i][col + j] == color:
                    if self._grid[row + int(i/3)][col + int(j/3)] == 1 - color and self._grid[row + 2* int(i/3)][col + 2* int(j/3)] == 1 - color:
                        self._grid[row + int(i/3)][col + int(j/3)] = EMPTY
                        self._grid[row + 2* int(i/3)][col + 2* int(j/3)] = EMPTY
        
    # AI-assisted modification: AI suggested changing count >= 5 to
    # count == 5 so that only exactly five contiguous stones count as a win.
    # Our team adapted the response to BoardJRM, replaced relevant 19 values
    # with SIZE, and adjusted comments. See README.txt and llm-usage/.
    def CheckOmok(self, color):
        #1. horizontal
        for r in range(SIZE):
            count = 0
            for c in range(SIZE):
                if self._grid[r][c] == color:
                    count += 1
                else:
                    if count == 5:
                        return True
                    count = 0

            if count == 5:
                return True

        #2. vertical
        for c in range(SIZE):
            count = 0
            for r in range(SIZE):
                if self._grid[r][c] == color:
                    count += 1
                else:
                    if count == 5:
                        return True
                    count = 0
            
            if count == 5:
                return True

        #3. diagonal (\)
        for start in range(SIZE):
            count = 0
            r, c = 0, start
            while r < SIZE and c < SIZE:
                if self._grid[r][c] == color:
                    count += 1
                else:
                    if count == 5:
                        return True
                    count = 0
                r += 1
                c += 1
            if count == 5:
                return True

            if start > 0:
                count = 0
                r, c = start, 0
                while r < SIZE and c < SIZE:
                    if self._grid[r][c] == color:
                        count += 1
                    else:
                        if count == 5:
                            return True
                        count = 0
                    r += 1
                    c += 1
                if count == 5:
                    return True

        #4. diagonal (/)
        for start in range(SIZE):
            count = 0
            r, c = 18, start
            while r >= 0 and c < SIZE:
                if self._grid[r][c] == color:
                    count += 1
                else:
                    if count == 5:
                        return True
                    count = 0
                r -= 1
                c += 1
            if count == 5:
                return True

            if start < 18:
                count = 0
                r, c = start, 0
                while r >= 0 and c < SIZE:
                    if self._grid[r][c] == color:
                        count += 1
                    else:
                        if count == 5:
                            return True
                        count = 0
                    r -= 1
                    c += 1
                if count == 5:
                    return True

        return False
                    
    def FullBoard(self):
        for row in range(SIZE):
            for col in range(SIZE):
                if self.ValidPosition(row, col):
                    return False
                
        return True


    def PrintBoard(self):
        for row in self._grid:
            print(' '.join(map(str, row)))
