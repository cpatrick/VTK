/*=========================================================================

 Program:   Visualization Toolkit
 Module:    vtkPStructuredGridConnectivity.h

 Copyright (c) Ken Martin, Will Schroeder, Bill Lorensen
 All rights reserved.
 See Copyright.txt or http://www.kitware.com/Copyright.htm for details.

 This software is distributed WITHOUT ANY WARRANTY; without even
 the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
 PURPOSE.  See the above copyright notice for more information.

 =========================================================================*/
#ifndef UNSTRUCTUREDGHOSTZONESCOMMON_H_
#define UNSTRUCTUREDGHOSTZONESCOMMON_H_

// VTK includes
#include "vtkMathUtilities.h"
#include "vtkMPIUtilities.h"

// C/C++ includes
#include <cmath>
#include <iomanip>
#include <sstream>

//------------------------------------------------------------------------------
//    G L O B A L   D A T A
//------------------------------------------------------------------------------
double Origin[3]  = {0.0,0.0,0.0};
double Spacing[3] = {0.5,0.5,0.5};
int Dims[3]       = {50,50,50};

int Rank   = -1;
int NRanks = 0;

vtkUnstructuredGrid* Grid;

int CheckGrid(vtkUnstructuredGrid* ghostGrid, const int iteration)
{
  int rc = 0;

  int numOfErrors = 0;
  std::ostringstream out;
  std::ostringstream err;

  vtkMPIController* cntrl =
      vtkMPIController::SafeDownCast(
          vtkMultiProcessController::GetGlobalController());

  // check node fields by the iteration number
  vtkDoubleArray* nodeXYZ =
      vtkDoubleArray::SafeDownCast(
          ghostGrid->GetPointData()->GetArray("NodeXYZ"));
  assert("pre: nodeXYZ != NULL" && (nodeXYZ != NULL) );
  assert("pre: nodeXYZ numtuples mismatch!" &&
          (ghostGrid->GetNumberOfPoints()==nodeXYZ->GetNumberOfTuples()));
  assert("pre: nodeXYZ numcomponents mismatch!" &&
          (nodeXYZ->GetNumberOfComponents()==3));


  out.str("");
  err.str("");
  double pnt[3];
  double* ptr = static_cast<double*>(nodeXYZ->GetVoidPointer(0));
  for(vtkIdType nodeIdx=0; nodeIdx < ghostGrid->GetNumberOfPoints(); ++nodeIdx)
    {
    ghostGrid->GetPoint(nodeIdx,pnt);
    for(int dim=0; dim < 3; ++dim)
      {
      double actual   = ptr[nodeIdx*3+dim];
      double expected = pnt[dim]+static_cast<double>(iteration);
      if( ! vtkMathUtilities::NearlyEqual<double>(actual,expected) )
        {
        ++numOfErrors;
        ++rc;
        err << std::setprecision(5)
            << "\t[ERROR]: value mismatch at node=" << nodeIdx
            << " expected=" << expected
            << " actual=" << actual
            << " delta=" << std::fabs(actual-expected)
            << std::endl;
        } // END if
      } // END for all dimensions
    } // END for all nodes

  out << "[INFO]: " << numOfErrors << "/" << ghostGrid->GetNumberOfPoints()
      << " nodes appear wrong: " << std::endl;
  out << err.str();
  vtkMPIUtilities::SynchronizedPrintf(cntrl,"%s",out.str().c_str());

  // likewise, check cell-fields
  vtkDoubleArray* cellXYZ =
      vtkDoubleArray::SafeDownCast(
          ghostGrid->GetCellData()->GetArray("CentroidXYZ"));
  assert("pre: nodeXYZ numtuples mismatch!" &&
          (ghostGrid->GetNumberOfCells()==cellXYZ->GetNumberOfTuples()));
  assert("pre: nodeXYZ numcomponents mismatch!" &&
          (cellXYZ->GetNumberOfComponents()==3));

  numOfErrors = 0;
  out.str("");
  err.str("");
  double centroid[3];
  double* cptr = static_cast<double*>(cellXYZ->GetVoidPointer(0));
  vtkIdList* ptIds = vtkIdList::New();
  for(vtkIdType cellIdx=0; cellIdx < ghostGrid->GetNumberOfCells(); ++cellIdx)
    {
    ghostGrid->GetCellPoints(cellIdx,ptIds);
    assert("pre: numpoints per cell must be 8!" &&
            ptIds->GetNumberOfIds()==8);
    centroid[0] = 0.0;
    centroid[1] = 0.0;
    centroid[2] = 0.0;
    for(vtkIdType n=0; n < ptIds->GetNumberOfIds(); ++n)
      {
      vtkIdType idx = ptIds->GetId(n);
      ghostGrid->GetPoint(idx,pnt);
      centroid[0] += pnt[0];
      centroid[1] += pnt[1];
      centroid[2] += pnt[2];
      } // END for all cell nodes

    centroid[0] /= static_cast<double>(ptIds->GetNumberOfIds());
    centroid[1] /= static_cast<double>(ptIds->GetNumberOfIds());
    centroid[2] /= static_cast<double>(ptIds->GetNumberOfIds());

    for(int dim=0; dim < 3; ++dim)
      {
      double actual   = cptr[cellIdx*3+dim];
      double expected = centroid[dim]+static_cast<double>(iteration);
      if( ! vtkMathUtilities::NearlyEqual<double>(actual,expected) )
        {
        ++numOfErrors;
        ++rc;
        err << std::setprecision(5)
            << "\t[ERROR]: cell value mismatch at cell=" << cellIdx
            << " dimension=" << dim
            << " expected=" << expected
            << " actual=" << actual
            << " delta= " << std::fabs(actual-expected)
            << std::endl;
        } // END if
      } // END for all dimensions
    } // END for all cells

  out << "[INFO]: " << numOfErrors << "/" << ghostGrid->GetNumberOfCells()
      << " cells appear wrong: " << std::endl;
  out << err.str();
  vtkMPIUtilities::SynchronizedPrintf(cntrl,"%s",out.str().c_str());
  ptIds->Delete();
  return( rc );
}

//------------------------------------------------------------------------------
void UpdateGrid(const int iteration)
{
  // increment node fields by the iteration number
  vtkDoubleArray* nodeXYZ =
      vtkDoubleArray::SafeDownCast(
          Grid->GetPointData()->GetArray("NodeXYZ"));
  assert("pre: nodeXYZ != NULL" && (nodeXYZ != NULL) );
  assert("pre: nodeXYZ numtuples mismatch!" &&
          (Grid->GetNumberOfPoints()==nodeXYZ->GetNumberOfTuples()));
  assert("pre: nodeXYZ numcomponents mismatch!" &&
          (nodeXYZ->GetNumberOfComponents()==3));

  double* ptr = static_cast<double*>(nodeXYZ->GetVoidPointer(0));
  for(vtkIdType nodeIdx=0; nodeIdx < Grid->GetNumberOfPoints(); ++nodeIdx)
    {
    ptr[ nodeIdx*3   ] += static_cast<double>(iteration);
    ptr[ nodeIdx*3+1 ] += static_cast<double>(iteration);
    ptr[ nodeIdx*3+2 ] += static_cast<double>(iteration);
    } // END for all nodes

  // increment cell fields by the iteration number
  vtkDoubleArray* cellXYZ =
      vtkDoubleArray::SafeDownCast(
          Grid->GetCellData()->GetArray("CentroidXYZ"));
  assert("pre: nodeXYZ numtuples mismatch!" &&
          (Grid->GetNumberOfCells()==cellXYZ->GetNumberOfTuples()));
  assert("pre: nodeXYZ numcomponents mismatch!" &&
          (cellXYZ->GetNumberOfComponents()==3));

  double* cptr = static_cast<double*>(cellXYZ->GetVoidPointer(0));
  for(vtkIdType cellIdx=0; cellIdx < Grid->GetNumberOfCells(); ++cellIdx)
    {
    cptr[ cellIdx*3   ] += static_cast<double>(iteration);
    cptr[ cellIdx*3+1 ] += static_cast<double>(iteration);
    cptr[ cellIdx*3+2 ] += static_cast<double>(iteration);
    } // END for all cells
}

//------------------------------------------------------------------------------
void SetXYZCellField()
{
  vtkDoubleArray* centerXYZ = vtkDoubleArray::New();
  centerXYZ->SetName("CentroidXYZ");
  centerXYZ->SetNumberOfComponents(3);
  centerXYZ->SetNumberOfTuples( Grid->GetNumberOfCells() );
  double* ptr = static_cast<double*>(centerXYZ->GetVoidPointer(0));

  double centroid[3];
  vtkIdList* ptIds = vtkIdList::New();
  for(vtkIdType cell=0; cell < Grid->GetNumberOfCells(); ++cell)
    {
    centroid[0] = centroid[1] = centroid[2] = 0.0;
    Grid->GetCellPoints(cell,ptIds);
    for(vtkIdType n=0; n < ptIds->GetNumberOfIds(); ++n)
      {
      centroid[0] += Grid->GetPoint(ptIds->GetId(n))[0];
      centroid[1] += Grid->GetPoint(ptIds->GetId(n))[1];
      centroid[2] += Grid->GetPoint(ptIds->GetId(n))[2];
      } // END for all cell nodes

    centroid[0] /= static_cast<double>(ptIds->GetNumberOfIds());
    centroid[1] /= static_cast<double>(ptIds->GetNumberOfIds());
    centroid[2] /= static_cast<double>(ptIds->GetNumberOfIds());

    memcpy(&ptr[cell*3],centroid,3*sizeof(double));
    } // END for all cells

  Grid->GetCellData()->AddArray( centerXYZ );
  centerXYZ->Delete();
  ptIds->Delete();
}

//------------------------------------------------------------------------------
void SetXYZNodeField()
{
  vtkDoubleArray* nodeXYZ = vtkDoubleArray::New();
  nodeXYZ->SetName("NodeXYZ");
  nodeXYZ->SetNumberOfComponents(3);
  nodeXYZ->SetNumberOfTuples( Grid->GetNumberOfPoints() );
  double* ptr = static_cast<double*>(nodeXYZ->GetVoidPointer(0));

  for(vtkIdType node=0; node < Grid->GetNumberOfPoints(); ++node)
    {
    // copy the point coordinates in to the array
    memcpy(&ptr[node*3],Grid->GetPoint(node),3*sizeof(double));
    } // END for all cells

  Grid->GetPointData()->AddArray(nodeXYZ);
  nodeXYZ->Delete();
}

//------------------------------------------------------------------------------
void WriteDataSet(
      vtkUnstructuredGrid* grid, const std::string& file)
{
  std::ostringstream oss;
  oss << file << "-" << Rank << ".vtk";

  vtkUnstructuredGridWriter* writer = vtkUnstructuredGridWriter::New();
  writer->SetFileName(oss.str().c_str());
  writer->SetInputData( grid );
  writer->Update();
  writer->Delete();
}

//------------------------------------------------------------------------------
void GetPoint(
      const int i, const int j, const int k,double pnt[3])
{
  pnt[0] = Origin[0]+i*Spacing[0];
  pnt[1] = Origin[1]+j*Spacing[1];
  pnt[2] = Origin[2]+k*Spacing[2];
}

//------------------------------------------------------------------------------
// Some usefull extent macros
#define IMIN(ext) ext[0]
#define IMAX(ext) ext[1]
#define JMIN(ext) ext[2]
#define JMAX(ext) ext[3]
#define KMIN(ext) ext[4]
#define KMAX(ext) ext[5]

// Some useful IJK macros
#define I(ijk) ijk[0]
#define J(ijk) ijk[1]
#define K(ijk) ijk[2]

void GenerateDataSet()
{
  // STEP 0: partition the global extent to the number of processes
  vtkExtentRCBPartitioner* partitioner = vtkExtentRCBPartitioner::New();
  partitioner->SetGlobalExtent(0,Dims[0]-1,0,Dims[1]-1,0,Dims[2]-1);
  partitioner->SetNumberOfPartitions( NRanks );
  partitioner->Partition();

  // STEP 1: get the extent of this process
  int ext[6];
  partitioner->GetPartitionExtent(Rank,ext);
  partitioner->Delete();

  // STEP 2: Allocate the unstructured grid instance of this process
  int dataDescription = vtkStructuredData::GetDataDescriptionFromExtent(ext);
  int numNodes = vtkStructuredData::GetNumberOfNodes(ext,dataDescription);
  int numCells = vtkStructuredData::GetNumberOfCells(ext,dataDescription);

  int dims[3];
  vtkStructuredData::GetDimensionsFromExtent(ext,dims,dataDescription);

  vtkPoints* nodes = vtkPoints::New();
  nodes->SetDataTypeToDouble();
  nodes->SetNumberOfPoints(numNodes);
  double* nodesPtr = static_cast<double*>(nodes->GetVoidPointer(0));

  vtkIdTypeArray* globalIds = vtkIdTypeArray::New();
  globalIds->SetName("GlobalID");
  globalIds->SetNumberOfComponents(1);
  globalIds->SetNumberOfTuples(numNodes);
  vtkIdType* globalIdxPtr =
      static_cast<vtkIdType*>(globalIds->GetVoidPointer(0));

  Grid->Allocate(numCells,8);

  // STEP 3: Loop through the extent assigned in this process and update
  // the nodes and connectivity of the unstructured grid.
  const int hexNodeOffSet[]= {
        0, 0, 0,
        1, 0, 0,
        1, 1, 0,
        0, 1, 0,

        0, 0, 1,
        1, 0, 1,
        1, 1, 1,
        0, 1, 1,
    };

  vtkIdType cellIdx;
  vtkIdType globalNodeIdx;
  vtkIdType localNodeIdx;
  vtkIdType cell[8];
  for(int i=IMIN(ext); i < IMAX(ext); ++i)
    {
    for(int j=JMIN(ext); j < JMAX(ext); ++j)
      {
      for(int k=KMIN(ext); k < KMAX(ext); ++k)
        {

        // local ijk of the grid cell
        int lijk[3];
        I(lijk) = i-IMIN(ext);
        J(lijk) = j-JMIN(ext);
        K(lijk) = k-KMIN(ext);

       cellIdx = vtkStructuredData::ComputePointId(dims,lijk,dataDescription);

        for(int node=0; node < 8; ++node)
          {
          // local ijk of the node
          int ijk[3];
          I(ijk) = I(lijk)+hexNodeOffSet[node*3];
          J(ijk) = J(lijk)+hexNodeOffSet[node*3+1];
          K(ijk) = K(lijk)+hexNodeOffSet[node*3+2];
          localNodeIdx =
              vtkStructuredData::ComputePointId(dims,ijk,dataDescription);

          cell[node] = localNodeIdx;

          // global ijk of the node
          int IJK[3];
          I(IJK) = i+hexNodeOffSet[node*3];
          J(IJK) = j+hexNodeOffSet[node*3+1];
          K(IJK) = k+hexNodeOffSet[node*3+2];
          globalNodeIdx =
              vtkStructuredData::ComputePointId(Dims,IJK,dataDescription);

          globalIdxPtr[localNodeIdx] = globalNodeIdx;
          GetPoint(I(IJK),J(IJK),K(IJK),&nodesPtr[localNodeIdx*3]);
          } // END for all nodes

        Grid->InsertNextCell(VTK_HEXAHEDRON,8,cell);
        } // END for all k
      } // END for all j
    } // END for all i

  Grid->SetPoints(nodes);
  nodes->Delete();
  Grid->GetPointData()->AddArray(globalIds);
  globalIds->Delete();

  SetXYZCellField();
  SetXYZNodeField();
}



#endif /* UNSTRUCTUREDGHOSTZONESCOMMON_H_ */
