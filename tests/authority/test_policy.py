import pytest

from app.authority.policy import Authority, calculate_lines, resolve


@pytest.mark.parametrize(
    "amount,expected",
    [
        ("1.00", Authority.HOD),
        ("4999999.99", Authority.HOD),
        ("5000000.00", Authority.HOD),
        ("5000000.01", Authority.CHIEF_OF_STAFF),
        ("99999999.99", Authority.CHIEF_OF_STAFF),
        ("100000000.00", Authority.CHIEF_OF_STAFF),
        ("100000000.01", Authority.MD),
        ("499999999.99", Authority.MD),
        ("500000000.00", Authority.MD),
        ("500000000.01", Authority.BOARD),
    ],
)
@pytest.mark.parametrize(
    "offices,floor",
    [
        (set(), Authority.HOD),
        ({"hod"}, Authority.CHIEF_OF_STAFF),
        ({"chief_of_staff"}, Authority.MD),
        ({"md"}, Authority.BOARD),
        ({"hod", "md"}, Authority.BOARD),
    ],
)
def test_amount_boundaries_and_all_requester_floors(amount, expected, offices, floor):
    assert resolve(amount, offices).authority == max(expected, floor)


@pytest.mark.parametrize(
    "amount",
    [
        "-1",
        "0",
        "0.99",
        "NaN",
        "Infinity",
        "-Infinity",
        "1.001",
        "1e999",
        "1e2",
        "+1",
        " 1 ",
        "1_0",
        "bad",
    ],
)
def test_invalid_submission_amounts(amount):
    with pytest.raises(ValueError):
        resolve(amount, set())


def test_exact_line_rounding_and_total():
    assert calculate_lines([("0.5", "0.01"), ("1.5", "0.01")]) == (["0.01", "0.02"], "0.03")
    assert (
        calculate_lines(
            [
                ("1", "2890"),
                ("1", "3400"),
                ("1", "7450"),
                ("1", "1400"),
                ("1", "27500"),
                ("1", "29000"),
            ]
        )[1]
        == "71640.00"
    )


@pytest.mark.parametrize(
    "qty,price", [("0", "1"), ("-1", "1"), ("1.00001", "2"), ("1", "-1"), ("1", "0.001")]
)
def test_invalid_lines(qty, price):
    with pytest.raises(ValueError):
        calculate_lines([(qty, price)])
