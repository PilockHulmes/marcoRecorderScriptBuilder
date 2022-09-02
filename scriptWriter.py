import commandBuilderLib as clib

combination = [
    clib.recall(),
    clib.jumpFront(),
]

with open("script.mcr", "w", encoding="utf-8") as file:
    file.write(clib.join(combination))
