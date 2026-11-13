// Reverse() on an array, written expecting LINQ: a new reversed sequence, the array untouched.
int[] values = [1, 2, 3];
var reversed = values.Reverse();
Console.WriteLine($"{string.Join(",", reversed)} / {string.Join(",", values)}");
