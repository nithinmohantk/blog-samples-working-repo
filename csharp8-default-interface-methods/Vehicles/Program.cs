using System;

namespace CSharp8Demo
{
    class Program
    {
        static void Main(string[] args)
        {
            IVehicle bmw = new Bmw();
            bmw.DisplayMessage();
            bmw.DefaultMessage();

            IVehicle audi = new Audi();
            audi.DisplayMessage();
            audi.DefaultMessage();
        }
    }

    interface IVehicle
    {
        // No body: every implementing class must provide this one.
        void DisplayMessage();

        // A body: classes that say nothing about this method get this implementation.
        void DefaultMessage() { Console.WriteLine("I am inside the default method in the interface!"); }
    }

    public class Bmw : IVehicle
    {
        public void DisplayMessage()
        {
            Console.WriteLine("I am BMW!!!");
        }
    }

    public class Audi : IVehicle
    {
        public void DisplayMessage()
        {
            Console.WriteLine("I am AUDI!!!");
        }

        public void DefaultMessage() => Console.WriteLine("I am inside the Audi class!");
    }
}
