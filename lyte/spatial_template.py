"""Shared browser projection for authoring and standalone previews."""

# ruff: noqa: E501

PROJECTION_SCRIPT = r"""
function projectionTransform(coords,width,height,axes=[0,1],magnification=1){
  let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
  for(const point of coords){
    const x=point[axes[0]]||0,y=point[axes[1]]||0;
    minX=Math.min(minX,x);maxX=Math.max(maxX,x);
    minY=Math.min(minY,y);maxY=Math.max(maxY,y);
  }
  if(!coords.length){minX=minY=maxX=maxY=0;}
  const spanX=maxX-minX,spanY=maxY-minY;
  const pad=Math.max(24,Math.min(width,height)*0.08);
  const scale=Math.min((width-pad*2)/(spanX||1),(height-pad*2)/(spanY||1))*magnification;
  return {minX,minY,scale,offsetX:(width-spanX*scale)/2,offsetY:(height-spanY*scale)/2};
}
function projectedPoints(coords,width,height,axes=[0,1],magnification=1,transform=null){
  const view=transform||projectionTransform(coords,width,height,axes,magnification);
  return coords.map(point=>[
    view.offsetX+((point[axes[0]]||0)-view.minX)*view.scale,
    view.offsetY+((point[axes[1]]||0)-view.minY)*view.scale
  ]);
}
"""
