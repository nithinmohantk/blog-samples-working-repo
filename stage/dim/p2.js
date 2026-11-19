(()=>{const G=window.G,SN=window.SN,P=window.PARTS;
P.push(G.h2('Calling a default method'));
P.push(G.p('There is one rule that surprises people. Notice that the example declares its variables as <code>IVehicle</code>, not as <code>Bmw</code>. That is not style. A default method belongs to the interface, and a class that does not implement it does not have it as a member. This does not compile:'));
P.push(G.code('csharp',SN('experiments/01-call-through-class/Program.cs','class Bmw : IVehicle { }',null).trimEnd()));
P.push(G.code('text',SN('@r/02-experiments.txt','error CS1061:','\n')));
P.push(G.p('Assign the object to an <code>IVehicle</code> variable, or cast it, and the call works. In practice this matters less than it sounds, because code that depends on an interface usually holds the interface type anyway. It does mean a default method is not a way to give a class new public members.'));

P.push(G.h2('Adding a method to a published interface'));
P.push(G.p('This is the case the feature was designed for. An interface already has implementers, and a later version needs one more method. <code>ConsoleLogger</code> below was written against the first version and has not been touched. <code>TaggedLogger</code> was written later and has its own way to report an error.'));
P.push(G.code('csharp',SN('Evolve/Program.cs','    // Version 2 of an interface','\n\n    class Program')));
P.push(G.code('text',SN('@r/01-programs.txt','starting','\n-- experiments')));
P.push(G.p('The old class reports the error through the default body, which is written in terms of the one method the old class does have. That is the pattern to copy: a default implementation should be built from the interface\'s other members, because those are all it can rely on. An interface still has no instance fields, so a default method cannot keep state of its own.'));

P.push(G.h2('When two defaults collide'));
P.push(G.p('A class can implement many interfaces, so two of them can disagree. Here <code>IElectric</code> and <code>ILuxury</code> both replace the default that <code>IVehicle</code> provides, and <code>Car</code> implements both without choosing.'));
P.push(G.code('csharp',SN('experiments/02-two-defaults-clash/Program.cs','interface IVehicle','\n\nclass Program')));
P.push(G.p('The compiler does not guess. It stops:'));
P.push(G.code('text',SN('@r/02-experiments.txt','error CS8705:','\n')));
P.push(G.p('The fix is for the class to say what it wants. With a <code>Describe</code> method on <code>Car</code>, the program compiles, and each object gets the most specific body available to it:'));
P.push(G.code('csharp',SN('experiments/03-most-specific-wins/Program.cs','class Bike : IVehicle { }','\n\nclass Program')));
P.push(G.code('text',SN('@r/01-programs.txt','a vehicle',null).trimEnd()));
P.push(G.mer(G.MF+`
flowchart TD
    A["A call through the interface type"] --> B{"Does the class implement the method?"}
    B -- Yes --> C["The class's method runs"]
    B -- No --> D{"Does one interface give the most specific body?"}
    D -- Yes --> E["That interface's body runs"]
    D -- "No, two disagree" --> F["Compile error CS8705:<br>the class must choose"]
    style C fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202
    style E fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202
    style F fill:#FEF2F2,stroke:#D13212,stroke-width:2px,color:#991B1B`));

P.push(G.h2('When to use it'));
P.push(G.table(['Situation','Use a default implementation?','Why'],[
['Adding a member to an interface others already implement','Yes','Existing classes keep compiling, new ones can override'],
['A convenience method built from the interface\'s other members','Yes','One place for the logic, and implementers can still do better'],
['Shared behaviour that needs fields','No, use an abstract base class','An interface has no instance state'],
['Giving classes new public members','No','The method is reachable only through the interface type'],
['Code that must run on .NET Framework','No','The runtime support is not planned there']]));
P.push(G.p('Used with restraint this makes interfaces easier to live with over years. Used freely it turns an interface into a base class with worse tooling. My own rule will be to reach for it when an interface has to grow, and not when a new one is being designed.'));

P.push(G.h2('Key takeaways'));
P.push(G.ul([
'In C# 8.0 an interface method can have a body. Classes that do not implement the method get that body.',
'A class\'s own implementation always wins over the interface\'s.',
'A default method is called through the interface type. Calling it on a variable of the class type is compile error CS1061.',
'If two interfaces supply competing bodies, the compiler reports CS8705 and the class has to implement the method itself.',
'The feature needs runtime support: .NET Core 3.0, and not .NET Framework 4.8.',
'Its best use is adding a member to an interface that already has implementers.']));

P.push(G.callout('note','HOW THIS WAS CHECKED','Every listing in this post was compiled with the language version set to 8.0 and run, and the outputs and compiler errors are copied from that run: <a href="https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/44552918548" target="_blank" rel="noopener">GitHub Actions run 44552918548</a>, commit <code>ccbb0d9</code>. Three of the six projects are expected not to compile, and the run checks that each fails with exactly the error shown. The screenshots are from my own installation of the previews and that installation was not repeated for the run. The statement about .NET Framework 4.8 is from Microsoft\'s "Building C# 8.0" post and was not tested here.'));
P.push(window.GETCODE);
P.push(G.h2('References &amp; Further Reading'));
P.push(G.box([
G.ref('https://devblogs.microsoft.com/dotnet/building-c-8-0/','Building C# 8.0','Mads Torgersen on the planned features, including default implementations of interface members and platform support'),
G.ref('https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/csharp8-default-interface-methods','Sample code for this article','Two programs and four experiments, all compiled as C# 8.0')]));
})();
