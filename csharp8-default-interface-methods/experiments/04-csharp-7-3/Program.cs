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
        IVehicle bmw = new Bmw();
        bmw.DefaultMessage();
    }
}
