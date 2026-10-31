from src.calc import divide_round

def test_exact():
    assert divide_round(6, 3) == 2
