// Private use of the exact public ATen MPS hooks, not a product bridge.
#include <ATen/detail/MPSHooksInterface.h>
#include <cstdio>
#include <exception>
extern "C" int ken_mps_cap_experiment(double fraction,char* error,size_t length) noexcept{
 try{at::detail::getMPSHooks().setMemoryFraction(fraction);return 0;}
 catch(const std::exception& failure){std::snprintf(error,length,"%s",failure.what());return 1;}
 catch(...){std::snprintf(error,length,"unknown native MPS failure");return 1;}
}
