(()=>{const G=window.G,SN=window.SN,P=window.PARTS;
const B='https://www.dataa.dev/post-images/C-8.0-New-FeatureInterface-Default-Imple_132C8/';
const shot=(n,alt)=>{const s=n?'_'+n:'';return '<!-- wp:image {"linkDestination":"custom"} -->\n<figure class="wp-block-image"><a href="'+B+'image'+s+'.png"><img src="'+B+'image_thumb'+s+'.png" alt="'+alt+'"/></a></figure>\n<!-- /wp:image -->'};
P.push(G.p('C# 8.0 brings a change to something that has been fixed since the first version of the language: an interface can now give a method a body. A class that implements the interface and says nothing about that method gets the body from the interface. A class that wants its own version writes one, as before.'));
P.push(G.p('Until now every member of an interface had to be implemented by every class that implemented it. This post shows how to try the new behaviour with the first previews, what the rules are when you call such a method, and where it is useful.'));

P.push(G.h2('The problem'));
P.push(G.p('An interface is a promise, and once other people have written classes against it the promise is hard to change. Add one method to a published interface and every implementing class stops compiling until somebody adds that method. For a library with users you have never met, that is a breaking change.'));
P.push(G.p('The usual ways around it all cost something. An abstract base class can carry shared code, but a class has only one base class. Extension methods can add behaviour, but an implementer cannot replace them with something better. A second interface, the familiar <code>IThing2</code>, works and leaves the mess in the type names for good.'));
P.push(G.p('A default implementation answers this directly. The new method arrives with a body, existing implementers keep compiling, and any class that can do better overrides it.'));

P.push(G.h2('When will we get C# 8.0?'));
P.push(G.p('C# 8.0 is planned to ship along with .NET Core 3.0. Preview 1 of both .NET Core 3.0 and Visual Studio 2019 is available to try now.'));
P.push(G.p('One thing is different about this feature. Most language features are the compiler\'s work alone and run on any runtime. A method body in an interface needs the runtime to cooperate, so it depends on the platform. Microsoft has said that C# 8.0 will be supported on platforms that implement .NET Standard 2.1, that .NET Core 3.0 will be one of them, and that .NET Framework 4.8 will not. If your code has to run on .NET Framework, this feature is not coming to it.'));

P.push(G.h2('Setup'));
P.push(G.p('<strong>1.</strong> Download and install <a href="https://aka.ms/netcore3download">Preview 1 of .NET Core 3.0</a> and <a href="https://visualstudio.microsoft.com/vs/preview/">Preview 1 of Visual Studio 2019</a>.'));
P.push(shot(0,'Installing the .NET Core 3.0 and Visual Studio 2019 previews, screenshot 1 of 3'));
P.push(shot(3,'Installing the .NET Core 3.0 and Visual Studio 2019 previews, screenshot 2 of 3'));
P.push(shot(4,'Installing the .NET Core 3.0 and Visual Studio 2019 previews, screenshot 3 of 3'));
P.push(G.p('<strong>2.</strong> Start Visual Studio 2019 Preview, create a new project and choose "Console App (.NET Core)" as the project type.'));
P.push(shot(5,'Creating a Console App (.NET Core) project in Visual Studio 2019 Preview, screenshot 1 of 3'));
P.push(shot(6,'Creating a Console App (.NET Core) project in Visual Studio 2019 Preview, screenshot 2 of 3'));
P.push(shot(7,'Creating a Console App (.NET Core) project in Visual Studio 2019 Preview, screenshot 3 of 3'));
P.push(G.p('<strong>3.</strong> When the project is open, change its target framework to <strong>.NET Core 3.0</strong>. Right-click the project in Solution Explorer, choose Properties, and use the drop-down on the Application tab.'));
P.push(shot(8,'Project properties in Visual Studio 2019 Preview with the target framework set to .NET Core 3.0'));
P.push(G.p('The project also has to compile as C# 8.0. If the compiler is on an older language version it refuses the method body with this error:'));
P.push(G.code('text',SN('@r/02-experiments.txt','error CS8370:','\n')));
P.push(G.p('Setting <code>&lt;LangVersion&gt;8.0&lt;/LangVersion&gt;</code> in the project file fixes that.'));

P.push(G.h2('The example'));
P.push(G.p('The interface below has two methods. <code>DisplayMessage</code> has no body, so every class must implement it. <code>DefaultMessage</code> has one. <code>Bmw</code> leaves it alone. <code>Audi</code> supplies its own.'));
P.push(G.code('csharp',SN('Vehicles/Program.cs','using System;',null).trimEnd()));
P.push(G.p('This is what it prints:'));
P.push(G.code('text',SN('@r/01-programs.txt','I am BMW!!!','\n-- Evolve')));
P.push(G.p('The BMW gets the interface\'s body. The Audi gets its own, even though the variable is typed as <code>IVehicle</code>: the call goes to the most specific implementation the object has.'));
})();
