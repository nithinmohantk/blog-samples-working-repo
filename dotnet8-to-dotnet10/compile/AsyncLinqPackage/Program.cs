// The community System.Linq.Async package, used for LINQ over IAsyncEnumerable before the framework had its own.
List<int> numbers = await Numbers().Where(n => n % 2 == 0).ToListAsync();
Console.WriteLine(numbers.Count);

static async IAsyncEnumerable<int> Numbers()
{
    for (int i = 0; i < 10; i++) { await Task.Yield(); yield return i; }
}
