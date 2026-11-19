using System;

namespace CSharp8Demo
{
    // Version 2 of an interface that other teams already implement.
    // LogError is new. It has a body, so version 1 implementers keep compiling.
    public interface ILogger
    {
        void Log(string message);

        void LogError(Exception error) => Log("ERROR " + error.GetType().Name + ": " + error.Message);
    }

    // Written against version 1. Not touched since.
    public class ConsoleLogger : ILogger
    {
        public void Log(string message) => Console.WriteLine(message);
    }

    // Written against version 2, with its own idea of how to report an error.
    public class TaggedLogger : ILogger
    {
        public void Log(string message) => Console.WriteLine("[app] " + message);

        public void LogError(Exception error) => Console.WriteLine("[app] !! " + error.Message);
    }

    class Program
    {
        static void Main(string[] args)
        {
            var failure = new InvalidOperationException("the order was already shipped");
            foreach (ILogger logger in new ILogger[] { new ConsoleLogger(), new TaggedLogger() })
            {
                logger.Log("starting");
                logger.LogError(failure);
            }
        }
    }
}
