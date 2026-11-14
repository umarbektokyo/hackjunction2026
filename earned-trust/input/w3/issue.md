# REQ-W3: Option 3 runs in a thread

Source: CSE1100 programming exam, 06-11-2024, "Wadden Islands Ferry Company" (`Waddenislands/programming_exam_nov_2024.pdf`, page 4).
The base is the human-written exam solution in `Waddenislands/`; this change was written by an agent.

## Option 3 (existing behaviour)

The total amount of all tickets issued for a certain route (e.g., Texel – Vlieland; a route is
uni-directional, so Vlieland – Texel is a different route!) is calculated and shown on the screen.
The route is requested from the user through the command line. Example output:

    All tickets in the database for the route Terschelling -> Vlieland combined are worth 155 euros.

## Extension (this requirement)

While the current input file is rather small, it can be expected that the database will grow quite
large during the tourist season. Tickets need to stay available while running the Option 3 query.
That is why you should implement Option 3 to make use of threads. Please ensure that Option 3 is
executed in a thread.

## Standards that apply to every change

- At least one unit test per non-trivial method (constructors, getters, setters and methods that
  only read user input or files are exempt); aim for 75% line coverage.
- Nice programming style, checked with CheckStyle (`checkstyle.xml`): method length, number of
  parameters, cyclomatic complexity, Javadoc, line length.
- The menu loops; option 5 stops the program.
