using System;

interface IVehicle
{
    void DefaultMessage() { Console.WriteLine("default"); }
}

class Bmw : IVehicle { }

class Program
{
    static void Main()
    {
        Bmw bmw = new Bmw();
        bmw.DefaultMessage();   // the variable is a Bmw, and Bmw has no such member
    }
}
