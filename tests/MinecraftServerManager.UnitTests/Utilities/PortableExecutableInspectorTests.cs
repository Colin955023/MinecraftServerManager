using System.Buffers.Binary;
using System.Reflection.PortableExecutable;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.UnitTests.Utilities;

public sealed class PortableExecutableInspectorTests
{
    private static string LibraryPath => typeof(object).Assembly.Location;

    [Fact]
    public void TryReadMachine_ManagedLibrary_ReturnsMachine() =>
        Assert.NotNull(PortableExecutableInspector.TryReadMachine(LibraryPath));

    [Fact]
    public void TryReadExecutableMachine_Library_ReturnsNull() =>
        Assert.Null(PortableExecutableInspector.TryReadExecutableMachine(LibraryPath));

    [Theory]
    [InlineData(Machine.Amd64, 0x20B, true)]
    [InlineData(Machine.I386, 0x10B, false)]
    public void TryReadExecutableMachine_MinimalExecutable_ReturnsMachineAndBitness(Machine machine, ushort optionalMagic, bool is64Bit)
    {
        using var temp = new TempDirectory("msm-unittest-pe-");
        string path = temp.Combine("app.exe");
        File.WriteAllBytes(path, CreateMinimalExecutable(machine, optionalMagic));

        Machine? actual = PortableExecutableInspector.TryReadExecutableMachine(path);

        Assert.Equal(machine, actual);
        Assert.Equal(is64Bit, PortableExecutableInspector.Is64Bit(actual!.Value));
    }

    /// <summary>建立僅含 MZ、PE 簽章、COFF 標頭與可選標頭魔數的最小可執行檔位元組（非 DLL）</summary>
    private static byte[] CreateMinimalExecutable(Machine machine, ushort optionalMagic)
    {
        const int peOffset = 0x40;
        const int optionalHeaderSize = 0xF0;
        const int coffOffset = peOffset + 4;
        const ushort executableImage = 0x0002;
        byte[] bytes = new byte[coffOffset + 20 + optionalHeaderSize];
        bytes[0] = (byte)'M';
        bytes[1] = (byte)'Z';
        BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(0x3C), peOffset);
        bytes[peOffset] = (byte)'P';
        bytes[peOffset + 1] = (byte)'E';
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(coffOffset), (ushort)machine);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(coffOffset + 16), optionalHeaderSize);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(coffOffset + 18), executableImage);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(coffOffset + 20), optionalMagic);
        return bytes;
    }

    [Theory]
    [InlineData(new byte[0])]
    [InlineData(new byte[] { 0x4C, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 })]
    [InlineData(new byte[] { (byte)'M', (byte)'Z', 0x00, 0x01, 0x02 })]
    public void TryReadMachine_NotPortableExecutable_ReturnsNull(byte[] content)
    {
        using var temp = new TempDirectory("msm-unittest-pe-");
        string path = temp.Combine("fake.exe");
        File.WriteAllBytes(path, content);

        Assert.Null(PortableExecutableInspector.TryReadMachine(path));
        Assert.Null(PortableExecutableInspector.TryReadExecutableMachine(path));
    }

    [Fact]
    public void TryReadMachine_MissingFile_ReturnsNull()
    {
        using var temp = new TempDirectory("msm-unittest-pe-");

        Assert.Null(PortableExecutableInspector.TryReadMachine(temp.Combine("missing.exe")));
    }

    [Theory]
    [InlineData(Machine.Amd64, true)]
    [InlineData(Machine.Arm64, true)]
    [InlineData(Machine.IA64, true)]
    [InlineData(Machine.I386, false)]
    [InlineData(Machine.Arm, false)]
    public void Is64Bit_Machine_ReturnsExpected(Machine machine, bool expected) =>
        Assert.Equal(expected, PortableExecutableInspector.Is64Bit(machine));
}
