// Decodes audio files with a given bass.dll (the 32-bit one from the osu! folder) and prints where a
// click expected at 1.000 s lands. Used to check the offset rules in src/mpc/audio.py against the very
// decoder osu!stable ships. Nothing is played; device 0 is BASS's "no sound" device.
//   csc /nologo /platform:x86 /out:bass_probe.exe bass_probe.cs
//   bass_probe.exe <folder holding a COPY of bass.dll> <audio file> [more files]
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

class Probe
{
    [DllImport("kernel32", CharSet = CharSet.Unicode)] static extern bool SetDllDirectory(string path);
    [DllImport("bass.dll")] static extern bool BASS_Init(int device, int freq, int flags, IntPtr win, IntPtr clsid);
    [DllImport("bass.dll", CharSet = CharSet.Unicode)] static extern int BASS_StreamCreateFile(bool mem, string file, long offset, long length, uint flags);
    [DllImport("bass.dll")] static extern int BASS_ChannelGetData(int handle, [Out] short[] buffer, int length);
    [DllImport("bass.dll")] static extern int BASS_ErrorGetCode();
    [DllImport("bass.dll")] static extern uint BASS_GetVersion();
    [DllImport("bass.dll")] static extern bool BASS_ChannelGetInfo(int handle, out Info info);
    [DllImport("bass.dll")] static extern bool BASS_StreamFree(int handle);

    struct Info { public int freq, chans, flags, ctype, origres, plugin, sample; public IntPtr filename; }

    static int Main(string[] args)
    {
        SetDllDirectory(args[0]);
        if (!BASS_Init(0, 44100, 0, IntPtr.Zero, IntPtr.Zero)) { Console.WriteLine("BASS_Init failed " + BASS_ErrorGetCode()); return 1; }
        Console.WriteLine("BASS version {0:X8}", BASS_GetVersion());
        for (int a = 1; a < args.Length; a++)
        {
            foreach (uint extra in new uint[] { 0x20000, 0 })                    // with and without PRESCAN
            {
                int h = BASS_StreamCreateFile(false, args[a], 0, 0, 0x200000u | 0x80000000u | extra);
                if (h == 0) { Console.WriteLine("open failed {0}: {1}", BASS_ErrorGetCode(), args[a]); continue; }
                Info info; BASS_ChannelGetInfo(h, out info);
                var all = new List<short>();
                var buf = new short[65536];
                for (;;) { int got = BASS_ChannelGetData(h, buf, buf.Length * 2); if (got <= 0) break; for (int i = 0; i < got / 2; i++) all.Add(buf[i]); }
                BASS_StreamFree(h);
                int frames = all.Count / info.chans, lo = (int)(0.8 * info.freq), hi = Math.Min(frames, (int)(1.2 * info.freq));
                int peak = 0;
                for (int i = lo; i < hi; i++) peak = Math.Max(peak, Math.Abs((int)all[i * info.chans]));
                int first = -1;
                for (int i = lo; i < hi; i++) if (Math.Abs((int)all[i * info.chans]) > peak * 0.25) { first = i; break; }
                Console.WriteLine("{0,-22} {1,-8} length {2,10:F1} ms   click at {3,8:F2} ms  (error {4,6:F2})",
                    System.IO.Path.GetFileName(args[a]), extra != 0 ? "prescan" : "plain", frames * 1000.0 / info.freq,
                    first * 1000.0 / info.freq, first * 1000.0 / info.freq - 1000.0);
            }
        }
        return 0;
    }
}
