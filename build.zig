const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{ .preferred_optimize_mode = .ReleaseFast });
    const dice = b.addSharedLibrary(.{
        .name = "dicemath",
        .root_source_file = b.path("dicemath.zig"),
        .target = target,
        .optimize = optimize,
        .strip = true,
    });
    b.installArtifact(dice);
}
