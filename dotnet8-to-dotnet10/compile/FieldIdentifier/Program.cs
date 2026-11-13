// A class with a member called "field", read and written from a property accessor. Common in older code.
Console.WriteLine(new Reading { Value = 42 }.Value);

internal sealed class Reading
{
    private int field;

    public int Value
    {
        get { return field; }
        set { field = value; }
    }
}
