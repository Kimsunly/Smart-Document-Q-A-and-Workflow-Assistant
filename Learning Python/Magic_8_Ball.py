import random

question = input("What do you want to know ? ")
answer = random.randint(1, 9)
print( "Question:" + question)
print("Magic 8 Ball:")
if answer == 1:
  print("Yes - definitely.")
elif answer == 2:
  print("It is decidedly so.")
elif answer == 3:
  print("Without a doubt.")
elif answer == 4:
  print("Reply hazy, try agian.")
elif answer == 5:
  print("Ask again later.")
elif answer == 6:
  print("Better not tell you now.")
elif answer == 7:
  print("My sources say no.")
elif answer == 8:
  print("Outlook not so good.")
else:
  print("Very doubtful.")
