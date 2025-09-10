
Gryffindor = 0
Ravenclaw = 0
Hufflepuff = 0
Slytherin = 0

A1 = int(input("Do you like Dawn or Dusk?\n"
            "1.Dawn\n"
            "2.Dusk\n"))
if A1 == 1:
    Gryffindor += 1
    Ravenclaw += 1
elif A1 == 2:
    Hufflepuff += 1
    Slytherin += 1
else:
    print("Wrong input!!")
A2 = int(input("When I'm dead, I want people to remember me as:\n"
            "1.The good\n"
            "2.The great\n"
            "3.The wise\n"
            "4.The bold\n"))
if A2 == 1:
    Hufflepuff +=2
elif A2 == 2:
    Slytherin +=2
elif A2 == 3:
    Ravenclaw +=2
elif A2 == 4:
    Gryffindor+=2
else:
    print("Wrong Input!")
A3 = int(input("Which kind of instrument most pleases your ear?\n"
            "1.The violin\n"
            "2.The trumpet\n"
            "3.The piano\n"
            "4.The drum\n"))
if A3 == 1:
    Slytherin += 4
elif A3 == 2:
    Hufflepuff += 4
elif A3 == 3:
    Ravenclaw += 4
elif A3 == 4:
    Gryffindor += 4
else:
    print("Wrong Input!")

print("Gryffindor: " + str(Gryffindor))
print("Ravenclaw: " + str(Ravenclaw))
print("Slytherin: " + str(Slytherin))
print("Hufflepuff:" + str(Hufflepuff))

highest = max(Gryffindor,Ravenclaw, Hufflepuff, Slytherin)
print("Highest score:" + str(highest))