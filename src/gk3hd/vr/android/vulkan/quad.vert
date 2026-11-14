#version 450
layout(push_constant) uniform Quad { vec4 clip[4]; vec4 uv; } quad;
layout(location=0) out vec2 uv;
void main() {
    const int corners[6]=int[6](0,1,2,2,1,3);
    int corner=corners[gl_VertexIndex];
    gl_Position=quad.clip[corner];
    uv=vec2((corner&2)==0 ? quad.uv.x : quad.uv.z,
            (corner&1)==0 ? quad.uv.y : quad.uv.w);
}
