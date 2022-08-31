import commandBuilderLib as clib

combination = [
    clib.jumpFront(),
    clib.wait(200),
    clib.click("Left"),
    clib.jumpFarFront()
]

with open("script.mcr", "w", encoding="utf-8") as file:
    file.write(clib.join(combination))
