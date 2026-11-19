using System;

interface IVehicle { void Describe() { Console.WriteLine("a vehicle"); } }
interface IElectric : IVehicle { void IVehicle.Describe() { Console.WriteLine("an electric vehicle"); } }
interface ILuxury : IVehicle { void IVehicle.Describe() { Console.WriteLine("a luxury vehicle"); } }

class Car : IElectric, ILuxury { }   // which Describe does a Car get?

class Program
{
    static void Main() { ((IVehicle)new Car()).Describe(); }
}
