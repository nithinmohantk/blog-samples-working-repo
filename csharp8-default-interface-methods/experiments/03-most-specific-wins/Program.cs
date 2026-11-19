using System;

interface IVehicle { void Describe() { Console.WriteLine("a vehicle"); } }
interface IElectric : IVehicle { void IVehicle.Describe() { Console.WriteLine("an electric vehicle"); } }
interface ILuxury : IVehicle { void IVehicle.Describe() { Console.WriteLine("a luxury vehicle"); } }

class Bike : IVehicle { }
class Leaf : IElectric { }
class Car : IElectric, ILuxury
{
    public void Describe() { Console.WriteLine("an electric luxury car"); }   // the class settles it
}

class Program
{
    static void Main()
    {
        foreach (IVehicle vehicle in new IVehicle[] { new Bike(), new Leaf(), new Car() })
        {
            vehicle.Describe();
        }
    }
}
